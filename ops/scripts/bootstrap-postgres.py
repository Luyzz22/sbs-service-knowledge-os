"""Create the non-admin runtime role and apply migrations with the database administrator."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg import sql


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def connection_string(user: str, password: str, database: str) -> str:
    host = required("DATABASE_HOST")
    port = os.environ.get("DATABASE_PORT", "5432")
    sslmode = os.environ.get("DATABASE_SSLMODE", "require")
    return (
        f"host={host} port={port} dbname={database} user={user} password={password} "
        f"sslmode={sslmode} connect_timeout=15"
    )


def ensure_login_role(cursor, role: str, password: str) -> None:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
    action = "ALTER" if cursor.fetchone() else "CREATE"
    cursor.execute(
        sql.SQL(
            f"{action} ROLE {{}} WITH LOGIN PASSWORD {{}} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
        ).format(sql.Identifier(role), sql.Literal(password))
    )


def ensure_owner_role(cursor, role: str, admin_user: str) -> None:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
    action = "ALTER" if cursor.fetchone() else "CREATE"
    cursor.execute(
        sql.SQL(f"{action} ROLE {{}} WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS").format(
            sql.Identifier(role)
        )
    )
    cursor.execute(sql.SQL("GRANT {} TO {} WITH ADMIN OPTION").format(sql.Identifier(role), sql.Identifier(admin_user)))


def main() -> None:
    admin_user = required("DATABASE_ADMIN_USER")
    admin_password = required("DATABASE_ADMIN_PASSWORD")
    app_user = required("DATABASE_USER")
    app_password = required("DATABASE_PASSWORD")
    lifecycle_user = required("DATABASE_LIFECYCLE_USER")
    lifecycle_password = required("DATABASE_LIFECYCLE_PASSWORD")
    owner_role = os.environ.get("DATABASE_OWNER_ROLE", "hydraulikdoc_data_owner").strip()
    if not owner_role:
        raise RuntimeError("DATABASE_OWNER_ROLE must not be empty")
    database = required("DATABASE_NAME")

    with psycopg.connect(connection_string(admin_user, admin_password, "postgres")) as connection:
        with connection.cursor() as cursor:
            ensure_login_role(cursor, app_user, app_password)
            ensure_login_role(cursor, lifecycle_user, lifecycle_password)
            ensure_owner_role(cursor, owner_role, admin_user)
            for role in (app_user, lifecycle_user):
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(role))
                )

    migration = Path(__file__).resolve().parents[2] / "db" / "migrations" / "001_enterprise.sql"
    tables = (
        "tenants",
        "documents",
        "assets",
        "analysis_runs",
        "analysis_reviews",
        "incidents",
        "notice_acceptances",
        "privacy_requests",
        "audit_events",
    )
    mutable_tables = tables[:-1]
    with psycopg.connect(connection_string(admin_user, admin_password, database)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(83024177)")
            cursor.execute(migration.read_text(encoding="utf-8"))
            for table in tables:
                cursor.execute(
                    sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                        sql.Identifier(table),
                        sql.Identifier(owner_role),
                    )
                )
            for function in ("purge_expired_tenant_data(text)", "list_retention_tenant_ids()"):
                cursor.execute(
                    sql.SQL("ALTER FUNCTION {} OWNER TO {}").format(sql.SQL(function), sql.Identifier(owner_role))
                )
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            for role in (app_user, lifecycle_user):
                cursor.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(role)))
                cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
                cursor.execute(
                    sql.SQL("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {}").format(sql.Identifier(role))
                )
                cursor.execute(
                    sql.SQL("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {}").format(
                        sql.Identifier(role)
                    )
                )
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT ON TABLE {} TO {}").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in mutable_tables),
                    sql.Identifier(app_user),
                )
            )
            cursor.execute(
                sql.SQL("GRANT UPDATE ON TABLE documents, assets, analysis_runs TO {}").format(sql.Identifier(app_user))
            )
            cursor.execute(sql.SQL("GRANT SELECT, INSERT ON TABLE audit_events TO {}").format(sql.Identifier(app_user)))
            cursor.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(app_user))
            )
            cursor.execute(
                sql.SQL("REVOKE EXECUTE ON FUNCTION purge_expired_tenant_data(text) FROM {}").format(
                    sql.Identifier(app_user)
                )
            )
            cursor.execute(
                sql.SQL("REVOKE EXECUTE ON FUNCTION list_retention_tenant_ids() FROM {}").format(
                    sql.Identifier(app_user)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT ON TABLE tenants TO {}").format(sql.Identifier(lifecycle_user))
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, UPDATE ON TABLE documents TO {}").format(sql.Identifier(lifecycle_user))
            )
            cursor.execute(
                sql.SQL("GRANT SELECT, INSERT ON TABLE audit_events TO {}").format(sql.Identifier(lifecycle_user))
            )
            cursor.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
                    sql.Identifier(lifecycle_user)
                )
            )
            for function in ("purge_expired_tenant_data(text)", "list_retention_tenant_ids()"):
                cursor.execute(
                    sql.SQL("GRANT EXECUTE ON FUNCTION {} TO {}").format(
                        sql.SQL(function), sql.Identifier(lifecycle_user)
                    )
                )

    print('{"level":"info","event":"database_bootstrap_completed"}')


if __name__ == "__main__":
    main()
