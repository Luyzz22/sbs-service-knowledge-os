import os
import unittest
import uuid


@unittest.skipUnless(os.environ.get("RUN_POSTGRES_INTEGRATION") == "true", "PostgreSQL integration profile disabled")
class PostgresSecurityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg

        cls.psycopg = psycopg
        cls.app_dsn = os.environ["INTEGRATION_DATABASE_APP_URL"]
        cls.lifecycle_dsn = os.environ["INTEGRATION_DATABASE_LIFECYCLE_URL"]
        cls.admin_dsn = os.environ["INTEGRATION_DATABASE_ADMIN_URL"]
        cls.owner_role = os.environ.get("INTEGRATION_DATABASE_OWNER_ROLE", "hydraulikdoc_data_owner")
        suffix = uuid.uuid4().hex[:12]
        cls.tenant_a = f"integration-a-{suffix}"
        cls.tenant_b = f"integration-b-{suffix}"

    def test_rls_runtime_privileges_and_lifecycle_function(self) -> None:
        from psycopg.errors import InsufficientPrivilege

        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_a,))
                cursor.execute(
                    "INSERT INTO tenants (tenant_id, display_name) VALUES (%s,'A')",
                    (self.tenant_a,),
                )
                cursor.execute(
                    """INSERT INTO assets
                    (asset_id, tenant_id, name, site, criticality, status)
                    VALUES ('a1',%s,'A1','DE','high','active')""",
                    (self.tenant_a,),
                )

        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_b,))
                cursor.execute(
                    "INSERT INTO tenants (tenant_id, display_name) VALUES (%s,'B')",
                    (self.tenant_b,),
                )
                cursor.execute(
                    """INSERT INTO assets
                    (asset_id, tenant_id, name, site, criticality, status)
                    VALUES ('b1',%s,'B1','DE','high','active')""",
                    (self.tenant_b,),
                )

        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_a,))
                cursor.execute("SELECT asset_id FROM assets ORDER BY asset_id")
                self.assertEqual(cursor.fetchall(), [("a1",)])
                cursor.execute("SELECT tenant_id FROM tenants")
                self.assertEqual(cursor.fetchall(), [(self.tenant_a,)])
                cursor.execute(
                    """SELECT
                    has_table_privilege(current_user, 'assets', 'UPDATE'),
                    has_table_privilege(current_user, 'analysis_reviews', 'UPDATE'),
                    has_table_privilege(current_user, 'notice_acceptances', 'UPDATE'),
                    has_table_privilege(current_user, 'privacy_requests', 'UPDATE')"""
                )
                self.assertEqual(cursor.fetchone(), (True, False, False, False))
                cursor.execute(
                    """SELECT
                    has_column_privilege(current_user, 'incidents', 'status', 'UPDATE'),
                    has_column_privilege(current_user, 'incidents', 'details', 'UPDATE'),
                    has_column_privilege(current_user, 'incidents', 'tenant_id', 'UPDATE'),
                    has_column_privilege(current_user, 'incidents', 'root_cause', 'UPDATE'),
                    has_table_privilege(current_user, 'incident_events', 'INSERT'),
                    has_table_privilege(current_user, 'incident_events', 'UPDATE'),
                    has_table_privilege(current_user, 'incident_events', 'DELETE')"""
                )
                self.assertEqual(cursor.fetchone(), (True, False, False, True, True, False, False))
                incident_id = str(uuid.uuid4())
                cursor.execute(
                    """INSERT INTO incidents
                    (incident_id, tenant_id, asset_id, title, details, severity, status, created_by_token,
                     retention_until)
                    VALUES (%s,%s,'a1','Expired','','warning','closed','token',now() - interval '1 day')""",
                    (incident_id, self.tenant_a),
                )
                cursor.execute(
                    """INSERT INTO incident_events
                    (event_id, tenant_id, incident_id, event_type, new_status, actor_role, actor_token)
                    VALUES (%s,%s,%s,'created','new','technician','token')""",
                    (str(uuid.uuid4()), self.tenant_a, incident_id),
                )
                cursor.execute(
                    """INSERT INTO audit_events
                    (event_id, tenant_id, action, outcome, occurred_at, retention_until, event_hash)
                    VALUES (%s,%s,'integration.expired','success',now(),now() - interval '1 day',%s)""",
                    (str(uuid.uuid4()), self.tenant_a, "a" * 64),
                )

        with self.assertRaises(InsufficientPrivilege):
            with self.psycopg.connect(self.app_dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT purge_expired_tenant_data(%s)", (self.tenant_a,))

        for statement in (
            "CREATE TABLE runtime_must_not_create(id int)",
            "DELETE FROM audit_events",
            "DELETE FROM incident_events",
            "UPDATE incident_events SET actor_role='admin'",
        ):
            with self.assertRaises(InsufficientPrivilege):
                with self.psycopg.connect(self.app_dsn) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_a,))
                        cursor.execute(statement)

        with self.psycopg.connect(self.lifecycle_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tenant_id FROM list_retention_tenant_ids() WHERE tenant_id IN (%s,%s) ORDER BY tenant_id",
                    (self.tenant_a, self.tenant_b),
                )
                self.assertEqual(cursor.fetchall(), [(self.tenant_a,), (self.tenant_b,)])
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_a,))
                cursor.execute("SELECT purge_expired_tenant_data(%s)", (self.tenant_a,))
                purged = cursor.fetchone()[0]
                self.assertEqual(purged["audit_events"], 1)
                self.assertEqual((purged["incident_events"], purged["incidents"]), (1, 1))

        for statement in ("CREATE TABLE lifecycle_must_not_create(id int)", "DELETE FROM audit_events"):
            with self.assertRaises(InsufficientPrivilege):
                with self.psycopg.connect(self.lifecycle_dsn) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (self.tenant_a,))
                        cursor.execute(statement)

        with self.psycopg.connect(self.admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='assets'")
                self.assertEqual(cursor.fetchone()[0], self.owner_role)
                cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='public.assets'::regclass"
                )
                self.assertEqual(cursor.fetchone(), (True, True))
                cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid='public.tenants'::regclass"
                )
                self.assertEqual(cursor.fetchone(), (True, True))
                cursor.execute(
                    "SELECT proname, pg_get_userbyid(proowner) FROM pg_proc "
                    "WHERE proname IN ('purge_expired_tenant_data','list_retention_tenant_ids') ORDER BY proname"
                )
                self.assertEqual(
                    cursor.fetchall(),
                    [
                        ("list_retention_tenant_ids", self.owner_role),
                        ("purge_expired_tenant_data", self.owner_role),
                    ],
                )

    def test_runtime_role_writes_hash_chained_audit_events(self) -> None:
        from compliance.audit import AuditOutcome
        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.repository import PostgresRepository

        settings = AppSettings.from_environment(
            {
                "APP_ENV": "test",
                "PERSISTENCE_BACKEND": "postgres",
                "AUDIT_HMAC_KEY": "integration-audit-key-" + "x" * 16,
                "DATABASE_URL": self.app_dsn,
            }
        )
        repository = PostgresRepository(settings)
        principal = UserPrincipal(
            "auditor", f"{self.tenant_a}-audit", "Auditor", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"]
        )
        for action in ("integration.audit.first", "integration.audit.second"):
            repository.emit_audit(principal, action=action, outcome=AuditOutcome.SUCCESS)
        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (principal.tenant_id,))
                cursor.execute("SELECT previous_hash, event_hash FROM audit_events ORDER BY sequence_id")
                rows = cursor.fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0][0])
        self.assertEqual(rows[1][0], rows[0][1])

    def test_runtime_role_reads_incident_lifecycles_per_tenant(self) -> None:
        from datetime import UTC, datetime, timedelta

        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.repository import PostgresRepository

        settings = AppSettings.from_environment(
            {
                "APP_ENV": "test",
                "PERSISTENCE_BACKEND": "postgres",
                "AUDIT_HMAC_KEY": "integration-audit-key-" + "x" * 16,
                "DATABASE_URL": self.app_dsn,
            }
        )
        repository = PostgresRepository(settings)
        own = UserPrincipal(
            "planner", f"{self.tenant_a}-kpi", "Planner", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"]
        )
        other = UserPrincipal(
            "planner", f"{self.tenant_b}-kpi", "Planner", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"]
        )
        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                for principal in (own, other):
                    cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (principal.tenant_id,))
                    cursor.execute(
                        "INSERT INTO tenants (tenant_id, display_name) VALUES (%s,'KPI')", (principal.tenant_id,)
                    )
        incident = repository.create_incident(own, asset_id="PU-1", title="Druckabfall", severity="p3", details="")
        repository.transition_incident(own, incident.incident_id, expected="new", target="acknowledged")
        repository.create_incident(other, asset_id="PU-9", title="Fremd", severity="p3", details="")

        since = datetime.now(UTC) - timedelta(days=1)
        lifecycles = repository.list_incident_lifecycles(own, since=since, limit=100)
        self.assertEqual([item.incident_id for item in lifecycles], [incident.incident_id])
        self.assertEqual(
            [(change.previous_status, change.new_status) for change in lifecycles[0].changes],
            [(None, "new"), ("new", "acknowledged")],
        )
        self.assertEqual(repository.list_incident_lifecycles(own, since=datetime.now(UTC), limit=100), ())

    def test_runtime_role_exports_every_personal_data_section(self) -> None:
        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.personal_data import PERSONAL_DATA_FIELDS
        from hydraulikdoc.repository import PostgresRepository
        from hydraulikdoc.security import ValidatedUpload

        settings = AppSettings.from_environment(
            {
                "APP_ENV": "test",
                "PERSISTENCE_BACKEND": "postgres",
                "AUDIT_HMAC_KEY": "integration-audit-key-" + "x" * 16,
                "DATABASE_URL": self.app_dsn,
            }
        )
        repository = PostgresRepository(settings)
        person = UserPrincipal(
            "exporter", f"{self.tenant_a}-dsr", "Exporter", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"]
        )
        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (person.tenant_id,))
                cursor.execute("INSERT INTO tenants (tenant_id, display_name) VALUES (%s,'DSR')", (person.tenant_id,))
        repository.register_document(
            person, ValidatedUpload(str(uuid.uuid4()), "Handbuch.pdf", "b" * 64, b"", "application/pdf")
        )
        incident = repository.create_incident(person, asset_id="PU-1", title="Leckage", severity="p3", details="")
        repository.transition_incident(person, incident.incident_id, expected="new", target="acknowledged")

        export = repository.subject_export(person)
        sections = {item.export_section for item in PERSONAL_DATA_FIELDS if item.export_section}
        self.assertLessEqual(sections, set(export))
        self.assertEqual(len(export["documents_uploaded"]), 1)
        self.assertEqual([item["incident_id"] for item in export["incidents_created"]], [incident.incident_id])
        self.assertEqual([item["new_status"] for item in export["incident_steps"]], ["new", "acknowledged"])
        self.assertEqual(export["reviews_given"], [])

    def test_audit_chain_verification_detects_tampering(self) -> None:
        from compliance.audit import AuditOutcome
        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.repository import PostgresRepository

        settings = AppSettings.from_environment(
            {
                "APP_ENV": "test",
                "PERSISTENCE_BACKEND": "postgres",
                "AUDIT_HMAC_KEY": "integration-audit-key-" + "x" * 16,
                "DATABASE_URL": self.app_dsn,
            }
        )
        repository = PostgresRepository(settings)
        admin = UserPrincipal(
            "auditor", f"{self.tenant_a}-chain", "Auditor", "admin", permissions=ROLE_PERMISSIONS["admin"]
        )
        for index in range(3):
            repository.emit_audit(
                admin, action="integration.chain.event", outcome=AuditOutcome.SUCCESS, metadata={"source_count": index}
            )
        previous_tz = os.environ.get("PGTZ")
        # Timestamps come back in the session time zone; verification must still hash them in UTC.
        os.environ["PGTZ"] = "Europe/Berlin"
        try:
            report = repository.verify_audit_chain(admin)
            self.assertEqual((report.intact, report.event_count), (True, 3))
            with self.psycopg.connect(self.admin_dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """UPDATE audit_events SET metadata = '{"source_count": 99}'::jsonb
                        WHERE sequence_id = (SELECT min(sequence_id) + 1 FROM audit_events WHERE tenant_id = %s)""",
                        (admin.tenant_id,),
                    )
            broken = repository.verify_audit_chain(admin)
        finally:
            if previous_tz is None:
                os.environ.pop("PGTZ", None)
            else:
                os.environ["PGTZ"] = previous_tz
        self.assertEqual((broken.intact, broken.reason), (False, "HASH_MISMATCH"))
        self.assertEqual(broken.broken_sequence, report.first_sequence + 1)

    def test_legal_hold_suspends_purge_until_released(self) -> None:
        from datetime import UTC, datetime, timedelta

        from psycopg.errors import InsufficientPrivilege

        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.repository import PostgresRepository
        from hydraulikdoc.security import ValidatedUpload

        def repository_for(dsn: str) -> PostgresRepository:
            return PostgresRepository(
                AppSettings.from_environment(
                    {
                        "APP_ENV": "test",
                        "PERSISTENCE_BACKEND": "postgres",
                        "AUDIT_HMAC_KEY": "integration-audit-key-" + "x" * 16,
                        "DATABASE_URL": dsn,
                    }
                )
            )

        runtime, lifecycle = repository_for(self.app_dsn), repository_for(self.lifecycle_dsn)
        admin = UserPrincipal("legal", f"{self.tenant_a}-hold", "Legal", "admin", permissions=ROLE_PERMISSIONS["admin"])
        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (admin.tenant_id,))
                cursor.execute("INSERT INTO tenants (tenant_id, display_name) VALUES (%s,'Hold')", (admin.tenant_id,))
        incident = runtime.create_incident(admin, asset_id="PU-1", title="Gewährleistung", severity="p2", details="")
        document = runtime.register_document(
            admin, ValidatedUpload(str(uuid.uuid4()), "Prüfbericht.pdf", "c" * 64, b"", "application/pdf")
        )
        hold = runtime.create_legal_hold(
            admin,
            case_reference="LH-2026-014",
            reason_code="warranty_claim",
            record_classes=("incident", "uploaded_content"),
            review_at=datetime.now(UTC) + timedelta(days=30),
        )
        with self.psycopg.connect(self.admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE incidents SET retention_until = now() - interval '1 day' WHERE tenant_id = %s",
                    (admin.tenant_id,),
                )
                cursor.execute(
                    "UPDATE documents SET retention_until = now() - interval '1 day' WHERE tenant_id = %s",
                    (admin.tenant_id,),
                )

        self.assertEqual(lifecycle.list_expired_documents(admin), ())
        held = lifecycle.purge_expired_records(admin)
        self.assertEqual((held["incidents"], held["incident_events"]), (0, 0))
        self.assertEqual([item.incident_id for item in runtime.list_incidents(admin)], [incident.incident_id])

        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (admin.tenant_id,))
                with self.assertRaises(InsufficientPrivilege):
                    cursor.execute("UPDATE legal_holds SET record_classes = ARRAY['audit_event']")
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (admin.tenant_id,))
                with self.assertRaises(InsufficientPrivilege):
                    cursor.execute("DELETE FROM legal_holds")

        runtime.release_legal_hold(admin, hold.hold_id)
        self.assertEqual([item.document_id for item in lifecycle.list_expired_documents(admin)], [document.document_id])
        released = lifecycle.purge_expired_records(admin)
        self.assertEqual(released["incidents"], 1)
        self.assertGreaterEqual(released["incident_events"], 1)
        self.assertEqual(released["legal_holds"], 0)


if __name__ == "__main__":
    unittest.main()
