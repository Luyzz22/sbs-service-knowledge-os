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
                self.assertEqual((purged["document_events"], purged["documents"]), (0, 0))

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

    def test_privacy_queue_records_the_case_with_column_grants(self) -> None:
        from psycopg.errors import InsufficientPrivilege

        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.repository import PostgresRepository, PrivacyTransitionRejected

        repository = PostgresRepository(
            AppSettings.from_environment(
                {
                    "APP_ENV": "test",
                    "PERSISTENCE_BACKEND": "postgres",
                    "AUDIT_HMAC_KEY": "integration-audit-key-" + "x" * 16,
                    "DATABASE_URL": self.app_dsn,
                }
            )
        )
        tenant = f"{self.tenant_a}-dsr-queue"
        employee = UserPrincipal(
            "employee", tenant, "Employee", "technician", permissions=ROLE_PERMISSIONS["technician"]
        )
        dpo = UserPrincipal("dpo", tenant, "DPO", "admin", permissions=ROLE_PERMISSIONS["admin"])
        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                cursor.execute("INSERT INTO tenants (tenant_id, display_name) VALUES (%s,'DSR')", (tenant,))
        request = repository.create_privacy_request(employee, "erasure")
        own = repository.create_privacy_request(dpo, "access")
        with self.assertRaisesRegex(PrivacyTransitionRejected, "PRIVACY_OWN_REQUEST"):
            repository.decide_privacy_request(dpo, own.request_id, expected="submitted", target="identity_verified")

        repository.decide_privacy_request(dpo, request.request_id, expected="submitted", target="identity_verified")
        repository.decide_privacy_request(dpo, request.request_id, expected="identity_verified", target="in_review")
        denied = repository.decide_privacy_request(
            dpo,
            request.request_id,
            expected="in_review",
            target="denied",
            decision_reason="legal_hold",
            evidence_reference="DSR-2026-031",
        )
        self.assertEqual((denied.status, denied.decision_reason), ("denied", "legal_hold"))
        self.assertIsNotNone(denied.completed_at)
        self.assertEqual(
            [(item.status, item.evidence_reference) for item in repository.list_privacy_requests(employee)],
            [("denied", "DSR-2026-031")],
        )
        self.assertEqual(repository.list_privacy_queue(dpo)[0].request_id, own.request_id)

        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                with self.assertRaises(InsufficientPrivilege):
                    cursor.execute("UPDATE privacy_requests SET request_type = 'access', requested_at = now()")

    def test_document_control_release_flow_and_history(self) -> None:
        from datetime import UTC, datetime, timedelta

        from psycopg.errors import InsufficientPrivilege

        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.governance import AIProvenance, GroundedAnswer, SourceCitation, UseCase
        from hydraulikdoc.repository import DocumentControl, PostgresRepository, require_document_deletion
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

        def upload(name: str, digest: str) -> ValidatedUpload:
            return ValidatedUpload(str(uuid.uuid4()), name, digest * 64, b"", "application/pdf")

        def code(error: BaseException) -> str:
            return str(error.args[0])

        runtime, lifecycle = repository_for(self.app_dsn), repository_for(self.lifecycle_dsn)
        runtime.check_schema()
        tenant = f"{self.tenant_a}-docs"
        supervisor = ROLE_PERMISSIONS["supervisor"]
        author = UserPrincipal("author", tenant, "Author", "supervisor", permissions=supervisor)
        approver = UserPrincipal("approver", tenant, "Approver", "supervisor", permissions=supervisor)
        technician = UserPrincipal("tech", tenant, "Tech", "technician", permissions=ROLE_PERMISSIONS["technician"])
        outsider = UserPrincipal("approver", f"{self.tenant_b}-docs", "Other", "supervisor", permissions=supervisor)
        review = datetime.now(UTC) + timedelta(days=180)

        first = runtime.register_document(author, upload("Handbuch.pdf", "d"), DocumentControl("1", "BA-HA-250"))
        self.assertEqual((first.release_status, first.usable_for_answers), ("draft", False))
        with self.assertRaises(ValueError) as not_indexed:
            runtime.release_document(approver, first.document_id, review_due_at=review)
        self.assertEqual(code(not_indexed.exception), "DOCUMENT_NOT_INDEXED")
        runtime.mark_document_indexed(author, first.document_id, 12)
        self.assertFalse(runtime.list_documents(approver)[0].usable_for_answers)

        for principal, expected in ((technician, "DOCUMENT_RELEASE_REQUIRED"), (author, "FOUR_EYES_RELEASE_REQUIRED")):
            with self.assertRaises(PermissionError) as denied:
                runtime.release_document(principal, first.document_id, review_due_at=review)
            self.assertEqual(code(denied.exception), expected)
        with self.assertRaises(KeyError):
            runtime.release_document(outsider, first.document_id, review_due_at=review)
        with self.assertRaises(ValueError) as late:
            runtime.release_document(approver, first.document_id, review_due_at=review + timedelta(days=400))
        self.assertEqual(code(late.exception), "DOCUMENT_REVIEW_DATE_INVALID")

        released = runtime.release_document(approver, first.document_id, review_due_at=review)
        self.assertEqual((released.document.release_status, released.superseded), ("released", None))
        stored = runtime.list_documents(author)[0]
        self.assertEqual((stored.usable_for_answers, stored.release_recorded, stored.is_own), (True, True, True))
        self.assertEqual((stored.revision, stored.document_number, stored.review_due_at), ("1", "BA-HA-250", review))
        self.assertFalse(runtime.list_documents(approver)[0].is_own)
        with self.assertRaises(PermissionError):
            require_document_deletion(technician, runtime, first.document_id)

        answer = GroundedAnswer.create(
            text="Ölwechsel nach 4000 Betriebsstunden.",
            citations=(SourceCitation(first.document_id, "Handbuch.pdf", 7, "chunk-1", 0.9, "1"),),
            provenance=AIProvenance("azure-openai", "integration", "snapshot", "swedencentral"),
            use_case=UseCase.MAINTENANCE_ASSISTANCE,
        )
        runtime.record_answer(technician, "Wann ist der Ölwechsel fällig?", answer)

        with self.assertRaises(ValueError) as unchanged:
            runtime.register_document(author, upload("Neu.pdf", "e"), DocumentControl("1", "", first.document_id))
        self.assertEqual(code(unchanged.exception), "DOCUMENT_REVISION_UNCHANGED")
        with self.assertRaises(ValueError) as foreign:
            runtime.register_document(outsider, upload("Neu.pdf", "e"), DocumentControl("2", "", first.document_id))
        self.assertEqual(code(foreign.exception), "DOCUMENT_SUPERSEDES_INVALID")
        second = runtime.register_document(
            approver, upload("Neu.pdf", "e"), DocumentControl("2", "", first.document_id)
        )
        self.assertEqual((second.document_number, second.supersedes_document_id), ("BA-HA-250", first.document_id))
        with self.assertRaises(ValueError) as pending:
            runtime.register_document(author, upload("Auch.pdf", "f"), DocumentControl("3", "", first.document_id))
        self.assertEqual(code(pending.exception), "DOCUMENT_SUPERSEDES_PENDING")
        runtime.mark_document_indexed(approver, second.document_id, 14)

        replaced = runtime.release_document(author, second.document_id, review_due_at=review)
        self.assertIsNotNone(replaced.superseded)
        self.assertEqual(replaced.superseded.document_id, first.document_id)
        self.assertEqual(replaced.superseded_answer_count, 1)
        by_id = {item.document_id: item for item in runtime.list_documents(technician)}
        self.assertEqual(
            (by_id[first.document_id].release_status, by_id[first.document_id].withdrawal_reason),
            ("withdrawn", "superseded"),
        )
        self.assertTrue(by_id[second.document_id].usable_for_answers)
        with self.assertRaises(ValueError) as final:
            runtime.release_document(approver, first.document_id, review_due_at=review)
        self.assertEqual(code(final.exception), "DOCUMENT_WITHDRAWN")

        later = review + timedelta(days=30)
        self.assertEqual(
            runtime.confirm_document_review(approver, second.document_id, review_due_at=later).review_due_at, later
        )
        history = runtime.list_document_events(approver, first.document_id)
        self.assertEqual(
            [(item.event_type, item.reason_code, item.is_own) for item in history],
            [("uploaded", None, False), ("released", None, True), ("withdrawn", "superseded", False)],
        )
        self.assertEqual(runtime.list_document_events(outsider, first.document_id), ())
        steps = runtime.subject_export(approver)["document_steps"]
        self.assertEqual(sorted(item["event_type"] for item in steps), ["released", "review_confirmed", "uploaded"])

        # A row from before document control: released without a release date, by nobody on record.
        legacy = runtime.register_document(author, upload("Alt.pdf", "a"))
        runtime.mark_document_indexed(author, legacy.document_id, 3)
        with self.psycopg.connect(self.admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET release_status='released', revision='' WHERE document_id=%s",
                    (legacy.document_id,),
                )
        grandfathered = {item.document_id: item for item in runtime.list_documents(approver)}[legacy.document_id]
        self.assertEqual((grandfathered.usable_for_answers, grandfathered.release_recorded), (True, False))
        with self.assertRaises(ValueError) as unrecorded:
            runtime.confirm_document_review(approver, legacy.document_id, review_due_at=review)
        self.assertEqual(code(unrecorded.exception), "DOCUMENT_RELEASE_NOT_RECORDED")
        formal = runtime.release_document(approver, legacy.document_id, review_due_at=review)
        self.assertTrue(formal.document.release_recorded)

        withdrawn = runtime.withdraw_document(approver, second.document_id, "safety_notice")
        self.assertEqual((withdrawn.document.release_status, withdrawn.cited_answer_count), ("withdrawn", 0))
        with self.assertRaises(ValueError) as invalid:
            runtime.withdraw_document(approver, legacy.document_id, "superseded")
        self.assertEqual(code(invalid.exception), "DOCUMENT_WITHDRAWAL_REASON_INVALID")

        for statement in ("UPDATE document_events SET actor_role='admin'", "DELETE FROM document_events"):
            with self.assertRaises(InsufficientPrivilege):
                with self.psycopg.connect(self.app_dsn) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                        cursor.execute(statement)
        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (outsider.tenant_id,))
                cursor.execute("SELECT count(*) FROM document_events")
                self.assertEqual(cursor.fetchone()[0], 0)

        # The history leaves with the document: first the events, then the row they point to.
        runtime.delete_document(approver, first.document_id)
        self.assertEqual(lifecycle.purge_expired_records(approver)["documents"], 1)
        self.assertEqual(runtime.list_document_events(approver, first.document_id), ())
        remaining = {item.document_id: item for item in runtime.list_documents(approver)}
        self.assertIsNone(remaining[second.document_id].supersedes_document_id)

    def test_review_queue_rules_question_retention_and_quality_records(self) -> None:
        from datetime import UTC, datetime, timedelta

        from hydraulikdoc.ai_quality import answer_quality
        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.governance import AIProvenance, GroundedAnswer, ReviewStatus, SourceCitation, UseCase
        from hydraulikdoc.repository import DocumentControl, PostgresRepository
        from hydraulikdoc.security import ValidatedUpload

        runtime = PostgresRepository(
            AppSettings.from_environment(
                {
                    "APP_ENV": "test",
                    "PERSISTENCE_BACKEND": "postgres",
                    "AUDIT_HMAC_KEY": "integration-audit-key-" + "x" * 16,
                    "DATABASE_URL": self.app_dsn,
                }
            )
        )
        runtime.check_schema()
        tenant = f"{self.tenant_a}-reviews"
        technician = ROLE_PERMISSIONS["technician"]
        asker = UserPrincipal("asker", tenant, "Asker", "technician", permissions=technician)
        colleague = UserPrincipal("colleague", tenant, "Colleague", "technician", permissions=technician)
        expert = UserPrincipal("expert", tenant, "Expert", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"])
        outsider = UserPrincipal(
            "expert", f"{self.tenant_b}-reviews", "Other", "supervisor", permissions=ROLE_PERMISSIONS["supervisor"]
        )

        def code(error: BaseException) -> str:
            return str(error.args[0])

        document = runtime.register_document(
            asker,
            ValidatedUpload(str(uuid.uuid4()), "Handbuch.pdf", "e" * 64, b"", "application/pdf"),
            DocumentControl("3", "BA-PU-7"),
        )
        runtime.mark_document_indexed(asker, document.document_id, 20)
        runtime.release_document(expert, document.document_id, review_due_at=datetime.now(UTC) + timedelta(days=90))

        def ask(use_case: UseCase, question: str, cited: bool = True) -> GroundedAnswer:
            citations = (SourceCitation(document.document_id, "Handbuch.pdf", 4, "chunk-4", 0.8, "3"),) if cited else ()
            answer = GroundedAnswer.create(
                text="Der Betriebsdruck beträgt 210 bar [S1]." if cited else "Keine Evidenz.",
                citations=citations,
                provenance=AIProvenance("azure-openai", "integration", "snapshot", "swedencentral"),
                use_case=use_case,
            )
            runtime.record_answer(asker, question, answer)
            return answer

        safety = ask(UseCase.SAFETY_RELEVANT_DIAGNOSIS, "  Darf die Pumpe mit 260 bar laufen?  ")
        ordinary = ask(UseCase.MAINTENANCE_ASSISTANCE, "Welcher Betriebsdruck gilt?")
        escalated = ask(UseCase.MAINTENANCE_ASSISTANCE, "Welches Öl ist zulässig?", cited=False)

        # The asker sees all three; a colleague only the one that needs a second person, with its question.
        own = {item.answer.answer_id: item for item in runtime.list_review_queue(asker)}
        self.assertEqual(set(own), {safety.answer_id, ordinary.answer_id, escalated.answer_id})
        self.assertTrue(all(item.is_own for item in own.values()))
        self.assertEqual(own[safety.answer_id].question, "Darf die Pumpe mit 260 bar laufen?")
        self.assertIsNone(own[ordinary.answer_id].question)
        (waiting,) = runtime.list_review_queue(colleague)
        self.assertEqual((waiting.answer.answer_id, waiting.is_own), (safety.answer_id, False))
        self.assertEqual(waiting.answer.citations, safety.citations)
        self.assertEqual(waiting.answer.provenance.model_snapshot, "snapshot")
        self.assertEqual(runtime.list_review_queue(outsider), ())

        with self.assertRaises(PermissionError) as four_eyes:
            runtime.record_review(asker, safety.answer_id, ReviewStatus.ACCEPTED)
        self.assertEqual(code(four_eyes.exception), "FOUR_EYES_REVIEW_REQUIRED")
        with self.assertRaises(KeyError):
            runtime.record_review(outsider, safety.answer_id, ReviewStatus.ACCEPTED)
        with self.assertRaises(ValueError) as no_reason:
            runtime.record_review(colleague, safety.answer_id, ReviewStatus.REJECTED, "TECHNICAL_REJECTION")
        self.assertEqual(code(no_reason.exception), "REVIEW_REASON_REQUIRED")

        # Escalation stores the question; only an expert decides, and the decision clears it.
        runtime.record_review(
            asker, escalated.answer_id, ReviewStatus.NEEDS_EXPERT, question="Welches Öl ist zulässig?"
        )
        with self.assertRaises(PermissionError) as needs_expert:
            runtime.record_review(colleague, escalated.answer_id, ReviewStatus.REJECTED, "incomplete")
        self.assertEqual(code(needs_expert.exception), "EXPERT_REVIEW_REQUIRED")
        queue = {item.answer.answer_id: item for item in runtime.list_review_queue(expert)}
        self.assertEqual(set(queue), {safety.answer_id, escalated.answer_id})
        self.assertEqual(queue[escalated.answer_id].question, "Welches Öl ist zulässig?")
        self.assertEqual(
            [(item.status, item.reviewer_role, item.is_own) for item in queue[escalated.answer_id].reviews],
            [(ReviewStatus.NEEDS_EXPERT, "technician", False)],
        )
        runtime.record_review(expert, escalated.answer_id, ReviewStatus.REJECTED, "incomplete")
        with self.assertRaises(ValueError) as decided:
            runtime.record_review(expert, escalated.answer_id, ReviewStatus.ACCEPTED)
        self.assertEqual(code(decided.exception), "REVIEW_ALREADY_DECIDED")

        # A withdrawn source can no longer back an accepted answer.
        runtime.record_review(asker, ordinary.answer_id, ReviewStatus.ACCEPTED)
        runtime.withdraw_document(expert, document.document_id, "incorrect")
        with self.assertRaises(ValueError) as withdrawn:
            runtime.record_review(colleague, safety.answer_id, ReviewStatus.ACCEPTED)
        self.assertEqual(code(withdrawn.exception), "REVIEW_SOURCE_NOT_RELEASED")
        runtime.record_review(colleague, safety.answer_id, ReviewStatus.REJECTED, "outdated_source")
        self.assertEqual(runtime.list_review_queue(expert), ())

        with self.psycopg.connect(self.admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM analysis_runs WHERE tenant_id=%s AND review_question IS NOT NULL", (tenant,)
                )
                self.assertEqual(cursor.fetchone()[0], 0)

        export = runtime.subject_export(colleague)
        self.assertEqual(
            [(item["status"], item["reason_code"], item["reviewer_role"]) for item in export["reviews_given"]],
            [("rejected", "outdated_source", "technician")],
        )
        self.assertTrue(all(item["review_question"] is None for item in runtime.subject_export(asker)["analysis_runs"]))

        since = datetime.now(UTC) - timedelta(days=1)
        records = runtime.list_answer_quality(expert, since=since, limit=10)
        by_id = {item.answer_id: item for item in records}
        self.assertEqual(
            {key: (item.review_status, item.rejection_reason, item.escalated) for key, item in by_id.items()},
            {
                safety.answer_id: ("rejected", "outdated_source", False),
                ordinary.answer_id: ("accepted", None, False),
                escalated.answer_id: ("rejected", "incomplete", True),
            },
        )
        self.assertEqual(by_id[escalated.answer_id].document_ids, ())
        self.assertTrue(all(item.decided_at is not None for item in records))
        self.assertEqual(len(runtime.list_answer_quality(expert, since=since, limit=2)), 2)
        self.assertEqual(runtime.list_answer_quality(outsider, since=since, limit=10), ())
        quality = answer_quality(records, runtime.list_documents(expert))
        self.assertEqual((quality.answers, quality.accepted, quality.rejected, quality.without_evidence), (3, 1, 2, 1))

    def test_operating_limits_release_flow_column_grants_and_purge(self) -> None:
        from datetime import UTC, datetime, timedelta

        from psycopg.errors import InsufficientPrivilege

        from hydraulikdoc.auth import ROLE_PERMISSIONS, UserPrincipal
        from hydraulikdoc.config import AppSettings
        from hydraulikdoc.operating_limits import LimitValues, released_limits
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

        def code(error: BaseException) -> str:
            return str(error.args[0])

        runtime, lifecycle = repository_for(self.app_dsn), repository_for(self.lifecycle_dsn)
        runtime.check_schema()
        tenant = f"{self.tenant_a}-limits"
        supervisor = ROLE_PERMISSIONS["supervisor"]
        technician = UserPrincipal("tech", tenant, "Tech", "technician", permissions=ROLE_PERMISSIONS["technician"])
        approver = UserPrincipal("approver", tenant, "Approver", "supervisor", permissions=supervisor)
        outsider = UserPrincipal("approver", f"{self.tenant_b}-limits", "Other", "supervisor", permissions=supervisor)
        with self.psycopg.connect(self.app_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                cursor.execute("INSERT INTO tenants (tenant_id, display_name) VALUES (%s,'Limits')", (tenant,))
        runtime.upsert_asset(
            approver,
            asset_id="PRESSE-04",
            name="Presse 04",
            site="Werk 1",
            manufacturer="",
            model="HA-250",
            criticality="high",
        )
        manual = runtime.register_document(
            technician, ValidatedUpload(str(uuid.uuid4()), "Handbuch.pdf", "9" * 64, b"", "application/pdf")
        )
        runtime.mark_document_indexed(technician, manual.document_id, 20)
        runtime.release_document(approver, manual.document_id, review_due_at=datetime.now(UTC) + timedelta(days=90))

        values = LimitValues(pressure_warning_bar=230.0, pressure_critical_bar=250.0, water_warning_pct=0.08)
        first = runtime.propose_operating_limits(
            technician,
            "PRESSE-04",
            values,
            source_reference="BA-HA-250 Rev. 1, Kapitel 4.2",
            source_document_id=manual.document_id,
            source_page=12,
        )
        self.assertEqual((first.version, first.status, first.is_own), (1, "draft", True))
        self.assertEqual((first.source_document_name, first.source_withdrawn), ("Handbuch.pdf", False))
        with self.assertRaises(ValueError) as pending:
            runtime.propose_operating_limits(approver, "PRESSE-04", values, source_reference="Zweiter Vorschlag")
        self.assertEqual(code(pending.exception), "OPERATING_LIMITS_PENDING")
        with self.assertRaises(ValueError) as unknown:
            runtime.propose_operating_limits(outsider, "PRESSE-04", values, source_reference="Fremder Mandant")
        self.assertEqual(code(unknown.exception), "OPERATING_LIMITS_ASSET_UNKNOWN")
        with self.assertRaises(PermissionError) as role:
            runtime.release_operating_limits(technician, first.limit_set_id)
        self.assertEqual(code(role.exception), "OPERATING_LIMITS_RELEASE_REQUIRED")
        with self.assertRaises(KeyError):
            runtime.release_operating_limits(outsider, first.limit_set_id)

        released = runtime.release_operating_limits(approver, first.limit_set_id)
        self.assertEqual((released.limits.status, released.superseded), ("released", None))
        self.assertEqual(released.limits.values, values)

        second = runtime.propose_operating_limits(
            approver,
            "PRESSE-04",
            LimitValues(pressure_warning_bar=220.0, pressure_critical_bar=240.0),
            source_reference="Engineering-Entscheidung EN-2026-31",
        )
        with self.assertRaises(PermissionError) as four_eyes:
            runtime.release_operating_limits(approver, second.limit_set_id)
        self.assertEqual(code(four_eyes.exception), "FOUR_EYES_LIMITS_REQUIRED")
        replaced = runtime.release_operating_limits(
            UserPrincipal("approver-2", tenant, "Approver 2", "supervisor", permissions=supervisor),
            second.limit_set_id,
        )
        self.assertEqual(replaced.superseded.limit_set_id if replaced.superseded else None, first.limit_set_id)
        sets = runtime.list_operating_limits(technician, "PRESSE-04")
        self.assertEqual([(item.version, item.status) for item in sets], [(2, "released"), (1, "superseded")])
        self.assertEqual(runtime.list_operating_limits(outsider), ())

        third = runtime.propose_operating_limits(
            technician,
            "PRESSE-04",
            values,
            source_reference="BA-HA-250 Rev. 1, Kapitel 4.2",
            source_document_id=manual.document_id,
            source_page=12,
        )
        runtime.withdraw_document(approver, manual.document_id, "obsolete")
        with self.assertRaises(ValueError) as withdrawn:
            runtime.release_operating_limits(approver, third.limit_set_id)
        self.assertEqual(code(withdrawn.exception), "OPERATING_LIMITS_SOURCE_NOT_RELEASED")
        superseded_first = {item.limit_set_id: item for item in runtime.list_operating_limits(approver)}
        self.assertTrue(superseded_first[first.limit_set_id].source_withdrawn)
        rejected = runtime.reject_operating_limits(technician, third.limit_set_id, "replaced_by_proposal")
        self.assertEqual(rejected.status, "rejected")

        export = runtime.subject_export(technician)["operating_limit_steps"]
        self.assertEqual(
            [(item["version"], item["step"]) for item in export], [(1, "proposed"), (3, "proposed"), (3, "rejected")]
        )

        # Released values cannot be edited in place, and nothing can be deleted by the runtime role.
        for statement in (
            "UPDATE operating_limits SET pressure_critical_bar = 400",
            "UPDATE operating_limits SET source_reference = 'geändert'",
            "UPDATE operating_limits SET proposed_by_token = 'x'",
            "DELETE FROM operating_limits",
        ):
            with self.subTest(statement), self.assertRaises(InsufficientPrivilege):
                with self.psycopg.connect(self.app_dsn) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                        cursor.execute(statement)

        # Superseded and rejected sets expire with audit retention; the set in force stays.
        with self.psycopg.connect(self.admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE operating_limits SET retention_until = now() - interval '1 day'
                    WHERE tenant_id = %s AND retention_until IS NOT NULL""",
                    (tenant,),
                )
        self.assertEqual(lifecycle.purge_expired_records(approver)["operating_limits"], 2)
        remaining = runtime.list_operating_limits(approver, "PRESSE-04")
        self.assertEqual([(item.version, item.status) for item in remaining], [(2, "released")])
        self.assertEqual(released_limits(remaining, "PRESSE-04"), remaining[0])


if __name__ == "__main__":
    unittest.main()
