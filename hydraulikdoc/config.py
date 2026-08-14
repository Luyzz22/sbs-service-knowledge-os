"""Fail-closed configuration for the HydraulikDoc enterprise runtime."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse


class ConfigurationError(RuntimeError):
    """Raised when a release profile is unsafe or incomplete."""


class RuntimeEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AuthMode(StrEnum):
    LOCAL = "local"
    ENTRA_PROXY = "entra_proxy"


class AIBackend(StrEnum):
    DISABLED = "disabled"
    AZURE = "azure"


class PersistenceBackend(StrEnum):
    MEMORY = "memory"
    POSTGRES = "postgres"


def _read_secret(
    name: str,
    values: Mapping[str, str],
    *,
    default: str | None = None,
) -> str | None:
    file_path = values.get(f"{name}_FILE")
    if file_path:
        path = Path(file_path)
        if not path.is_file():
            raise ConfigurationError(f"Secret file for {name} is not readable")
        return path.read_text(encoding="utf-8").strip()
    value = values.get(name, default)
    return value.strip() if isinstance(value, str) else value


def _bool(name: str, values: Mapping[str, str], default: bool = False) -> bool:
    raw = values.get(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _positive_int(name: str, values: Mapping[str, str], default: int) -> int:
    try:
        parsed = int(values.get(name, str(default)))
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be positive")
    return parsed


def _enum(enum_type, name: str, values: Mapping[str, str], default: str):
    raw = values.get(name, default).strip().lower()
    try:
        return enum_type(raw)
    except ValueError as error:
        choices = ", ".join(item.value for item in enum_type)
        raise ConfigurationError(f"{name} must be one of: {choices}") from error


def _https_endpoint(name: str, value: str | None, required: bool) -> str | None:
    if not value:
        if required:
            raise ConfigurationError(f"{name} is required")
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ConfigurationError(f"{name} must be an HTTPS endpoint without credentials")
    return value.rstrip("/")


def _database_url(values: Mapping[str, str]) -> str | None:
    explicit = _read_secret("DATABASE_URL", values)
    if explicit:
        return explicit
    host = values.get("DATABASE_HOST")
    user = values.get("DATABASE_USER")
    database = values.get("DATABASE_NAME")
    password = _read_secret("DATABASE_PASSWORD", values)
    if not host or not user or not database or not password:
        return None
    port = values.get("DATABASE_PORT", "5432")
    sslmode = values.get("DATABASE_SSLMODE", "require")
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/"
        f"{quote_plus(database)}?sslmode={quote_plus(sslmode)}"
    )


@dataclass(frozen=True)
class AppSettings:
    """Immutable configuration with production release gates."""

    environment: RuntimeEnvironment
    auth_mode: AuthMode
    ai_backend: AIBackend
    persistence_backend: PersistenceBackend
    default_tenant_id: str
    public_base_url: str | None
    database_url: str | None = field(repr=False)
    audit_hmac_key: str = field(repr=False)
    local_users_json: str | None = field(default=None, repr=False)
    azure_region: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_chat_deployment: str | None = None
    azure_embedding_deployment: str | None = None
    azure_embedding_dimensions: int = 1536
    azure_document_intelligence_endpoint: str | None = None
    azure_search_endpoint: str | None = None
    azure_blob_endpoint: str | None = None
    azure_blob_container: str = "documents"
    azure_search_index: str = "hydraulikdoc-knowledge-v1"
    azure_search_semantic: bool = True
    azure_use_managed_identity: bool = True
    azure_openai_key: str | None = field(default=None, repr=False)
    azure_document_intelligence_key: str | None = field(default=None, repr=False)
    azure_search_key: str | None = field(default=None, repr=False)
    azure_model_snapshot: str = "deployment-defined"
    max_upload_bytes: int = 50 * 1024 * 1024
    max_question_chars: int = 2000
    max_video_bytes: int = 200 * 1024 * 1024
    malware_scan_timeout_seconds: int = 300
    session_idle_minutes: int = 30
    require_human_review: bool = True
    allow_multimodal: bool = False
    compliance_release_approved: bool = False
    deployment_evidence_id: str | None = None
    ai_evaluation_evidence_id: str | None = None
    retention_policy_approved: bool = False
    retention_policy_id: str | None = None
    auto_migrate_database: bool = False
    privacy_notice_version: str = "2026-08-14"
    ai_notice_version: str = "2026-08-14"

    @property
    def is_production(self) -> bool:
        return self.environment is RuntimeEnvironment.PRODUCTION

    @property
    def azure_ready(self) -> bool:
        return bool(
            self.ai_backend is AIBackend.AZURE
            and self.azure_openai_endpoint
            and self.azure_chat_deployment
            and self.azure_embedding_deployment
            and self.azure_document_intelligence_endpoint
            and self.azure_search_endpoint
            and self.azure_blob_endpoint
        )

    @property
    def release_state(self) -> str:
        if (
            self.is_production
            and self.compliance_release_approved
            and self.retention_policy_approved
            and self.azure_ready
        ):
            return "configured"
        if self.azure_ready:
            return "gated"
        return "development"

    def local_users(self) -> Mapping[str, object]:
        if not self.local_users_json:
            return {}
        try:
            parsed = json.loads(self.local_users_json)
        except json.JSONDecodeError as error:
            raise ConfigurationError("LOCAL_USERS_JSON must contain valid JSON") from error
        if not isinstance(parsed, dict):
            raise ConfigurationError("LOCAL_USERS_JSON must be a JSON object")
        return parsed

    def validate(self) -> AppSettings:
        errors: list[str] = []
        if not self.default_tenant_id or len(self.default_tenant_id) > 80:
            errors.append("DEFAULT_TENANT_ID must contain 1 to 80 characters")
        if self.azure_embedding_dimensions not in {1536, 3072}:
            errors.append("AZURE_EMBEDDING_DIMENSIONS must be 1536 or 3072")
        if not 30 <= self.malware_scan_timeout_seconds <= 1800:
            errors.append("MALWARE_SCAN_TIMEOUT_SECONDS must be between 30 and 1800")

        if self.is_production:
            if self.auth_mode is not AuthMode.ENTRA_PROXY:
                errors.append("production requires AUTH_MODE=entra_proxy")
            if self.ai_backend is not AIBackend.AZURE:
                errors.append("production requires AI_BACKEND=azure")
            if self.persistence_backend is not PersistenceBackend.POSTGRES:
                errors.append("production requires PERSISTENCE_BACKEND=postgres")
            if not self.database_url:
                errors.append("production requires DATABASE_URL or complete DATABASE_* settings")
            if len(self.audit_hmac_key.encode("utf-8")) < 32:
                errors.append("production requires an AUDIT_HMAC_KEY of at least 32 bytes")
            if not self.public_base_url or not self.public_base_url.startswith("https://"):
                errors.append("production requires an HTTPS PUBLIC_BASE_URL")
            if not self.azure_use_managed_identity:
                errors.append("production requires AZURE_USE_MANAGED_IDENTITY=true")
            if any((self.azure_openai_key, self.azure_document_intelligence_key, self.azure_search_key)):
                errors.append("production forbids static Azure service keys; use Managed Identity")
            if self.azure_region not in {"germanywestcentral", "germanynorth"}:
                errors.append("production AZURE_REGION must be an approved German Azure region")
            if not self.compliance_release_approved:
                errors.append("production requires COMPLIANCE_RELEASE_APPROVED=true")
            if not self.deployment_evidence_id:
                errors.append("production requires DEPLOYMENT_EVIDENCE_ID")
            if not self.ai_evaluation_evidence_id:
                errors.append("production requires AI_EVALUATION_EVIDENCE_ID")
            if self.azure_model_snapshot == "deployment-defined":
                errors.append("production requires an evaluated AZURE_OPENAI_MODEL_SNAPSHOT")
            if not self.retention_policy_approved:
                errors.append("production requires RETENTION_POLICY_APPROVED=true")
            if not self.retention_policy_id:
                errors.append("production requires RETENTION_POLICY_ID")
            if not self.require_human_review:
                errors.append("production requires REQUIRE_HUMAN_REVIEW=true")
            if self.auto_migrate_database:
                errors.append("production forbids AUTO_MIGRATE_DATABASE; use the privileged bootstrap job")

        if self.ai_backend is AIBackend.AZURE:
            for name, value in (
                ("AZURE_OPENAI_ENDPOINT", self.azure_openai_endpoint),
                ("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", self.azure_document_intelligence_endpoint),
                ("AZURE_SEARCH_ENDPOINT", self.azure_search_endpoint),
                ("AZURE_BLOB_ENDPOINT", self.azure_blob_endpoint),
                ("AZURE_OPENAI_CHAT_DEPLOYMENT", self.azure_chat_deployment),
                ("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", self.azure_embedding_deployment),
            ):
                if not value:
                    errors.append(f"{name} is required for AI_BACKEND=azure")

        if errors:
            raise ConfigurationError("Unsafe runtime configuration:\n- " + "\n- ".join(errors))
        return self

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> AppSettings:
        values = environment if environment is not None else os.environ
        runtime = _enum(RuntimeEnvironment, "APP_ENV", values, RuntimeEnvironment.DEVELOPMENT.value)
        production = runtime is RuntimeEnvironment.PRODUCTION
        azure_openai_endpoint = _https_endpoint("AZURE_OPENAI_ENDPOINT", values.get("AZURE_OPENAI_ENDPOINT"), False)
        document_endpoint = _https_endpoint(
            "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT",
            values.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"),
            False,
        )
        search_endpoint = _https_endpoint("AZURE_SEARCH_ENDPOINT", values.get("AZURE_SEARCH_ENDPOINT"), False)
        blob_endpoint = _https_endpoint("AZURE_BLOB_ENDPOINT", values.get("AZURE_BLOB_ENDPOINT"), False)
        public_url = _https_endpoint("PUBLIC_BASE_URL", values.get("PUBLIC_BASE_URL"), production)
        audit_key = _read_secret(
            "AUDIT_HMAC_KEY",
            values,
            default="development-only-audit-key-change-me-0001",
        )
        if audit_key is None:
            raise ConfigurationError("AUDIT_HMAC_KEY must not be empty")
        settings = cls(
            environment=runtime,
            auth_mode=_enum(
                AuthMode,
                "AUTH_MODE",
                values,
                AuthMode.ENTRA_PROXY.value if production else AuthMode.LOCAL.value,
            ),
            ai_backend=_enum(
                AIBackend,
                "AI_BACKEND",
                values,
                AIBackend.AZURE.value if production else AIBackend.DISABLED.value,
            ),
            persistence_backend=_enum(
                PersistenceBackend,
                "PERSISTENCE_BACKEND",
                values,
                PersistenceBackend.POSTGRES.value if production else PersistenceBackend.MEMORY.value,
            ),
            default_tenant_id=values.get("DEFAULT_TENANT_ID", "development-tenant").strip(),
            public_base_url=public_url,
            database_url=_database_url(values),
            audit_hmac_key=audit_key,
            local_users_json=_read_secret("LOCAL_USERS_JSON", values),
            azure_region=values.get("AZURE_REGION", "").strip().lower() or None,
            azure_openai_endpoint=azure_openai_endpoint,
            azure_openai_api_version=values.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            azure_chat_deployment=values.get("AZURE_OPENAI_CHAT_DEPLOYMENT") or None,
            azure_embedding_deployment=values.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or None,
            azure_embedding_dimensions=_positive_int("AZURE_EMBEDDING_DIMENSIONS", values, 1536),
            azure_document_intelligence_endpoint=document_endpoint,
            azure_search_endpoint=search_endpoint,
            azure_blob_endpoint=blob_endpoint,
            azure_blob_container=values.get("AZURE_BLOB_CONTAINER", "documents"),
            azure_search_index=values.get("AZURE_SEARCH_INDEX", "hydraulikdoc-knowledge-v1"),
            azure_search_semantic=_bool("AZURE_SEARCH_SEMANTIC", values, True),
            azure_use_managed_identity=_bool("AZURE_USE_MANAGED_IDENTITY", values, True),
            azure_openai_key=_read_secret("AZURE_OPENAI_KEY", values),
            azure_document_intelligence_key=_read_secret("AZURE_DOCUMENT_INTELLIGENCE_KEY", values),
            azure_search_key=_read_secret("AZURE_SEARCH_KEY", values),
            azure_model_snapshot=values.get("AZURE_OPENAI_MODEL_SNAPSHOT", "deployment-defined"),
            max_upload_bytes=_positive_int("MAX_UPLOAD_BYTES", values, 50 * 1024 * 1024),
            max_question_chars=_positive_int("MAX_QUESTION_CHARS", values, 2000),
            max_video_bytes=_positive_int("MAX_VIDEO_BYTES", values, 200 * 1024 * 1024),
            malware_scan_timeout_seconds=_positive_int("MALWARE_SCAN_TIMEOUT_SECONDS", values, 300),
            session_idle_minutes=_positive_int("SESSION_IDLE_MINUTES", values, 30),
            require_human_review=_bool("REQUIRE_HUMAN_REVIEW", values, True),
            allow_multimodal=_bool("ENABLE_AZURE_MULTIMODAL", values, False),
            compliance_release_approved=_bool("COMPLIANCE_RELEASE_APPROVED", values, False),
            deployment_evidence_id=values.get("DEPLOYMENT_EVIDENCE_ID") or None,
            ai_evaluation_evidence_id=values.get("AI_EVALUATION_EVIDENCE_ID") or None,
            retention_policy_approved=_bool("RETENTION_POLICY_APPROVED", values, False),
            retention_policy_id=values.get("RETENTION_POLICY_ID") or None,
            auto_migrate_database=_bool("AUTO_MIGRATE_DATABASE", values, not production),
            privacy_notice_version=values.get("PRIVACY_NOTICE_VERSION", "2026-08-14"),
            ai_notice_version=values.get("AI_NOTICE_VERSION", "2026-08-14"),
        )
        return settings.validate()


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.from_environment()
