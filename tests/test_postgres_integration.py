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
                    """INSERT INTO audit_events
                    (event_id, tenant_id, action, outcome, occurred_at, retention_until, event_hash)
                    VALUES (%s,%s,'integration.expired','success',now(),now() - interval '1 day',%s)""",
                    (str(uuid.uuid4()), self.tenant_a, "a" * 64),
                )

        with self.assertRaises(InsufficientPrivilege):
            with self.psycopg.connect(self.app_dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT purge_expired_tenant_data(%s)", (self.tenant_a,))

        for statement in ("CREATE TABLE runtime_must_not_create(id int)", "DELETE FROM audit_events"):
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
                self.assertEqual(cursor.fetchone()[0]["audit_events"], 1)

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


if __name__ == "__main__":
    unittest.main()
