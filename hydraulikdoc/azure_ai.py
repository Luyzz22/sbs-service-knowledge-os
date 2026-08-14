"""Azure-only RAG pipeline with Managed Identity and tenant security trimming."""

from __future__ import annotations

import base64
import hashlib
import html
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

from compliance.audit import AuditOutcome

from .auth import UserPrincipal, require_permission
from .config import AppSettings
from .governance import (
    AIProvenance,
    GroundedAnswer,
    SourceCitation,
    UseCase,
    evaluate_use_case,
    system_prompt,
)
from .repository import DocumentRecord, EnterpriseRepository
from .security import (
    ValidatedUpload,
    bounded_untrusted_text,
    odata_literal,
    validate_question,
)

DOCUMENT_API_VERSION = "2024-11-30"
SEARCH_API_VERSION = "2024-07-01"
SEARCH_SEMANTIC_CONFIGURATION = "hydraulic-semantic"


class AzureServiceError(RuntimeError):
    """Safe service error that never contains customer payloads or credentials."""


def _required_endpoint(value: str | None, service: str) -> str:
    if not value:
        raise AzureServiceError(f"{service} endpoint is not configured")
    return value


@dataclass(frozen=True)
class ParsedPage:
    page: int
    content: str


@dataclass(frozen=True)
class SearchChunk:
    chunk_id: str
    tenant_id: str
    document_id: str
    display_name: str
    page: int
    section: str
    content: str
    content_vector: tuple[float, ...]


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    document_id: str
    display_name: str
    page: int
    content: str
    score: float | None


class AzureCredentialHeaders:
    """Issue scoped headers through Managed Identity or development-only keys."""

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._credential = None
        if settings.azure_use_managed_identity:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as error:
                raise AzureServiceError("azure-identity is not installed") from error
            self._credential = DefaultAzureCredential(exclude_interactive_browser_credential=settings.is_production)

    def headers(self, scope: str, key: str | None = None) -> dict[str, str]:
        if self._credential is not None:
            token = self._credential.get_token(scope)
            return {"Authorization": f"Bearer {token.token}"}
        if not key:
            raise AzureServiceError("No Azure credential is configured")
        return {"api-key": key}

    @property
    def credential(self):
        return self._credential


def _require_same_origin(operation_url: str, configured_endpoint: str) -> None:
    operation = urlparse(operation_url)
    configured = urlparse(configured_endpoint)
    if operation.scheme != "https" or operation.netloc != configured.netloc:
        raise AzureServiceError("Azure operation returned an unexpected endpoint")


class AzureDocumentParser:
    def __init__(self, settings: AppSettings, credentials: AzureCredentialHeaders) -> None:
        self._settings = settings
        self._credentials = credentials
        self._endpoint = _required_endpoint(
            settings.azure_document_intelligence_endpoint,
            "Azure Document Intelligence",
        )
        try:
            import httpx
        except ImportError as error:
            raise AzureServiceError("httpx is not installed") from error
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))

    def parse_pdf(self, content: bytes) -> tuple[ParsedPage, ...]:
        url = (
            f"{self._endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze"
            f"?api-version={DOCUMENT_API_VERSION}&outputContentFormat=markdown"
        )
        headers = self._credentials.headers(
            "https://cognitiveservices.azure.com/.default",
            self._settings.azure_document_intelligence_key,
        )
        headers["Content-Type"] = "application/pdf"
        response = self._client.post(url, headers=headers, content=content)
        if response.status_code != 202:
            raise AzureServiceError(f"Document parsing request failed ({response.status_code})")
        operation_url = response.headers.get("operation-location")
        if not operation_url:
            raise AzureServiceError("Document parsing response did not contain an operation URL")
        _require_same_origin(operation_url, self._endpoint)

        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            poll_headers = self._credentials.headers(
                "https://cognitiveservices.azure.com/.default",
                self._settings.azure_document_intelligence_key,
            )
            poll = self._client.get(operation_url, headers=poll_headers)
            if poll.status_code != 200:
                raise AzureServiceError(f"Document parsing status failed ({poll.status_code})")
            payload = poll.json()
            status = payload.get("status")
            if status == "succeeded":
                return self._pages(payload.get("analyzeResult", {}))
            if status in {"failed", "canceled"}:
                raise AzureServiceError("Document parsing did not succeed")
            time.sleep(1.0)
        raise AzureServiceError("Document parsing exceeded the processing deadline")

    @staticmethod
    def _pages(result: Mapping[str, Any]) -> tuple[ParsedPage, ...]:
        content = str(result.get("content", ""))
        pages: list[ParsedPage] = []
        for page_number, page in enumerate(result.get("pages", []), start=1):
            spans = page.get("spans", []) if isinstance(page, dict) else []
            fragments: list[str] = []
            for span in spans:
                offset = int(span.get("offset", 0))
                length = int(span.get("length", 0))
                if offset >= 0 and length > 0:
                    fragments.append(content[offset : offset + length])
            page_content = "\n".join(fragments).strip()
            if page_content:
                pages.append(ParsedPage(page_number, page_content))
        if not pages and content.strip():
            pages.append(ParsedPage(1, content.strip()))
        if not pages:
            raise AzureServiceError("Document parser returned no readable content")
        return tuple(pages)


class AzureOpenAIModels:
    def __init__(self, settings: AppSettings, credentials: AzureCredentialHeaders) -> None:
        self._settings = settings
        endpoint = _required_endpoint(settings.azure_openai_endpoint, "Azure OpenAI")
        try:
            from openai import AzureOpenAI
        except ImportError as error:
            raise AzureServiceError("openai is not installed") from error

        kwargs: dict[str, Any] = {
            "azure_endpoint": endpoint,
            "api_version": settings.azure_openai_api_version,
            "timeout": 60.0,
            "max_retries": 2,
        }
        if settings.azure_use_managed_identity:
            try:
                from azure.identity import get_bearer_token_provider
            except ImportError as error:
                raise AzureServiceError("azure-identity is not installed") from error
            kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
                credentials.credential, "https://cognitiveservices.azure.com/.default"
            )
        else:
            kwargs["api_key"] = settings.azure_openai_key
        self._client = AzureOpenAI(**kwargs)

    def embeddings(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        deployment = self._settings.azure_embedding_deployment
        if not deployment:
            raise AzureServiceError("Embedding deployment is not configured")
        vectors: list[tuple[float, ...]] = []
        for offset in range(0, len(texts), 16):
            response = self._client.embeddings.create(
                model=deployment,
                input=list(texts[offset : offset + 16]),
                dimensions=self._settings.azure_embedding_dimensions,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(tuple(item.embedding) for item in ordered)
        return tuple(vectors)

    def answer(self, question: str, context: str) -> str:
        deployment = self._settings.azure_chat_deployment
        if not deployment:
            raise AzureServiceError("Chat deployment is not configured")
        response = self._client.chat.completions.create(
            model=deployment,
            temperature=0.0,
            max_tokens=1400,
            messages=[
                {"role": "system", "content": system_prompt()},
                {
                    "role": "user",
                    "content": f"EVIDENZ\n{context}\n\nFRAGE\n{question}",
                },
            ],
        )
        text = response.choices[0].message.content
        if not text:
            raise AzureServiceError("The model returned an empty answer")
        return text.strip()


class AzureBlobStore:
    def __init__(self, settings: AppSettings, credentials: AzureCredentialHeaders) -> None:
        if not re.fullmatch(r"[a-z0-9-]{3,63}", settings.azure_blob_container):
            raise AzureServiceError("Invalid Azure Blob container name")
        self._settings = settings
        self._credentials = credentials
        self._endpoint = _required_endpoint(settings.azure_blob_endpoint, "Azure Blob Storage")
        try:
            import httpx
        except ImportError as error:
            raise AzureServiceError("httpx is not installed") from error
        self._client = httpx.Client(timeout=httpx.Timeout(90.0, connect=10.0))

    @staticmethod
    def _tenant_path(tenant_id: str) -> str:
        return hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:32]

    def _url(self, tenant_id: str, document_id: str) -> str:
        path = f"{self._tenant_path(tenant_id)}/{document_id}/original.pdf"
        return f"{self._endpoint}/{self._settings.azure_blob_container}/{quote(path, safe='/')}"

    def put(self, tenant_id: str, upload: ValidatedUpload) -> None:
        headers = self._credentials.headers("https://storage.azure.com/.default", None)
        headers.update(
            {
                "x-ms-version": "2023-11-03",
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": upload.content_type,
                "x-ms-meta-sha256": upload.sha256,
                "x-ms-meta-document-id": upload.document_id,
            }
        )
        response = self._client.put(self._url(tenant_id, upload.document_id), headers=headers, content=upload.content)
        if response.status_code not in {201, 202}:
            raise AzureServiceError(f"Document storage failed ({response.status_code})")

    def wait_until_clean(self, tenant_id: str, document_id: str) -> None:
        deadline = time.monotonic() + self._settings.malware_scan_timeout_seconds
        tag_url = self._url(tenant_id, document_id) + "?comp=tags"
        while time.monotonic() < deadline:
            headers = self._credentials.headers("https://storage.azure.com/.default", None)
            headers["x-ms-version"] = "2023-11-03"
            response = self._client.get(tag_url, headers=headers)
            if response.status_code != 200:
                raise AzureServiceError(f"Malware scan status lookup failed ({response.status_code})")
            result = None
            for key, value in re.findall(
                r"<Tag>\s*<Key>(.*?)</Key>\s*<Value>(.*?)</Value>\s*</Tag>",
                response.text,
                flags=re.DOTALL,
            ):
                if html.unescape(key).strip().casefold() == "malware scanning scan result":
                    result = html.unescape(value).strip()
                    break
            if result == "No threats found":
                return
            if result:
                raise AzureServiceError("Uploaded document did not pass malware scanning")
            time.sleep(2.0)
        raise AzureServiceError("Malware scanning exceeded the processing deadline")

    def delete(self, tenant_id: str, document_id: str) -> None:
        headers = self._credentials.headers("https://storage.azure.com/.default", None)
        headers["x-ms-version"] = "2023-11-03"
        response = self._client.delete(self._url(tenant_id, document_id), headers=headers)
        if response.status_code not in {202, 404}:
            raise AzureServiceError(f"Document storage deletion failed ({response.status_code})")


class AzureHybridSearch:
    def __init__(self, settings: AppSettings, credentials: AzureCredentialHeaders) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,126}[a-z0-9]", settings.azure_search_index):
            raise AzureServiceError("Invalid Azure AI Search index name")
        self._settings = settings
        self._credentials = credentials
        self._endpoint = _required_endpoint(settings.azure_search_endpoint, "Azure AI Search")
        self._index = settings.azure_search_index
        try:
            import httpx
        except ImportError as error:
            raise AzureServiceError("httpx is not installed") from error
        self._client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))

    def _headers(self) -> dict[str, str]:
        headers = self._credentials.headers("https://search.azure.com/.default", self._settings.azure_search_key)
        headers["Content-Type"] = "application/json"
        return headers

    def ensure_index(self) -> None:
        url = f"{self._endpoint}/indexes/{self._index}?api-version={SEARCH_API_VERSION}"
        response = self._client.get(url, headers=self._headers())
        if response.status_code == 200:
            return
        if response.status_code != 404:
            raise AzureServiceError(f"Search index inspection failed ({response.status_code})")
        schema = {
            "name": self._index,
            "fields": [
                {"name": "chunk_id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "tenant_id", "type": "Edm.String", "filterable": True},
                {"name": "document_id", "type": "Edm.String", "filterable": True},
                {"name": "display_name", "type": "Edm.String", "searchable": True, "filterable": True},
                {"name": "page", "type": "Edm.Int32", "filterable": True, "sortable": True},
                {"name": "section", "type": "Edm.String", "searchable": True, "filterable": True},
                {"name": "content", "type": "Edm.String", "searchable": True},
                {
                    "name": "content_vector",
                    "type": "Collection(Edm.Single)",
                    "searchable": True,
                    "dimensions": self._settings.azure_embedding_dimensions,
                    "vectorSearchProfile": "hydraulic-vector-profile",
                },
            ],
            "vectorSearch": {
                "algorithms": [
                    {
                        "name": "hydraulic-hnsw",
                        "kind": "hnsw",
                        "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"},
                    }
                ],
                "profiles": [{"name": "hydraulic-vector-profile", "algorithm": "hydraulic-hnsw"}],
            },
            "semantic": {
                "configurations": [
                    {
                        "name": SEARCH_SEMANTIC_CONFIGURATION,
                        "prioritizedFields": {
                            "titleField": {"fieldName": "display_name"},
                            "prioritizedContentFields": [{"fieldName": "content"}],
                            "prioritizedKeywordsFields": [{"fieldName": "section"}],
                        },
                    }
                ]
            },
        }
        created = self._client.put(url, headers=self._headers(), json=schema)
        if created.status_code not in {200, 201}:
            raise AzureServiceError(f"Search index creation failed ({created.status_code})")

    def upload(self, chunks: Sequence[SearchChunk]) -> None:
        url = f"{self._endpoint}/indexes/{self._index}/docs/index?api-version={SEARCH_API_VERSION}"
        for offset in range(0, len(chunks), 500):
            values = []
            for chunk in chunks[offset : offset + 500]:
                values.append(
                    {
                        "@search.action": "mergeOrUpload",
                        "chunk_id": chunk.chunk_id,
                        "tenant_id": chunk.tenant_id,
                        "document_id": chunk.document_id,
                        "display_name": chunk.display_name,
                        "page": chunk.page,
                        "section": chunk.section,
                        "content": chunk.content,
                        "content_vector": list(chunk.content_vector),
                    }
                )
            response = self._client.post(url, headers=self._headers(), json={"value": values})
            if response.status_code != 200:
                raise AzureServiceError(f"Search indexing failed ({response.status_code})")
            result = response.json().get("value", [])
            if any(not item.get("status") for item in result):
                raise AzureServiceError("At least one search document failed to index")

    def query(self, tenant_id: str, question: str, vector: Sequence[float]) -> tuple[SearchHit, ...]:
        url = f"{self._endpoint}/indexes/{self._index}/docs/search?api-version={SEARCH_API_VERSION}"
        payload: dict[str, Any] = {
            "search": question,
            "filter": f"tenant_id eq '{odata_literal(tenant_id)}'",
            "vectorQueries": [{"kind": "vector", "vector": list(vector), "fields": "content_vector", "k": 50}],
            "select": "chunk_id,document_id,display_name,page,content",
            "top": 8,
        }
        if self._settings.azure_search_semantic:
            payload.update(
                {
                    "queryType": "semantic",
                    "semanticConfiguration": SEARCH_SEMANTIC_CONFIGURATION,
                    "captions": "extractive|highlight-false",
                }
            )
        response = self._client.post(url, headers=self._headers(), json=payload)
        if response.status_code != 200:
            raise AzureServiceError(f"Search query failed ({response.status_code})")
        hits = []
        for item in response.json().get("value", []):
            score = item.get("@search.rerankerScore", item.get("@search.score"))
            hits.append(
                SearchHit(
                    chunk_id=str(item["chunk_id"]),
                    document_id=str(item["document_id"]),
                    display_name=str(item["display_name"]),
                    page=int(item["page"]),
                    content=str(item["content"]),
                    score=float(score) if score is not None else None,
                )
            )
        return tuple(hits)

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        search_url = f"{self._endpoint}/indexes/{self._index}/docs/search?api-version={SEARCH_API_VERSION}"
        index_url = f"{self._endpoint}/indexes/{self._index}/docs/index?api-version={SEARCH_API_VERSION}"
        for _ in range(100):
            response = self._client.post(
                search_url,
                headers=self._headers(),
                json={
                    "search": "*",
                    "filter": (
                        f"tenant_id eq '{odata_literal(tenant_id)}' and document_id eq '{odata_literal(document_id)}'"
                    ),
                    "select": "chunk_id",
                    "top": 1000,
                },
            )
            if response.status_code != 200:
                raise AzureServiceError(f"Search deletion lookup failed ({response.status_code})")
            values = [
                {"@search.action": "delete", "chunk_id": item["chunk_id"]} for item in response.json().get("value", [])
            ]
            if not values:
                return
            deleted = self._client.post(index_url, headers=self._headers(), json={"value": values})
            if deleted.status_code != 200 or any(not item.get("status") for item in deleted.json().get("value", [])):
                raise AzureServiceError("Search deletion failed")
        raise AzureServiceError("Search deletion exceeded the bounded batch limit")


def chunk_pages(
    pages: Iterable[ParsedPage],
    *,
    tenant_id: str,
    document_id: str,
    display_name: str,
    max_chars: int = 4200,
    overlap_chars: int = 400,
) -> tuple[tuple[str, int, str, str], ...]:
    chunks: list[tuple[str, int, str, str]] = []
    for page in pages:
        text = re.sub(r"\n{3,}", "\n\n", page.content).strip()
        section = "Seite " + str(page.page)
        heading = re.search(r"(?m)^#{1,6}\s+(.+)$", text)
        if heading:
            section = heading.group(1)[:160]
        position = 0
        sequence = 0
        while position < len(text):
            end = min(len(text), position + max_chars)
            if end < len(text):
                boundary = max(text.rfind("\n\n", position, end), text.rfind(". ", position, end))
                if boundary > position + max_chars // 2:
                    end = boundary + 1
            content = text[position:end].strip()
            if content:
                key = f"{tenant_id}:{document_id}:{page.page}:{sequence}"
                chunk_id = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()).decode().rstrip("=")
                chunks.append((chunk_id, page.page, section, content))
                sequence += 1
            if end >= len(text):
                break
            position = max(position + 1, end - overlap_chars)
    return tuple(chunks)


def has_valid_source_citations(text: str, source_count: int) -> bool:
    """Require at least one valid source marker whenever retrieval returned evidence."""
    if source_count <= 0:
        return True
    cited_sources = {int(item) for item in re.findall(r"\[S(\d+)\]", text)}
    return bool(cited_sources) and all(1 <= item <= source_count for item in cited_sources)


class AzureRAGService:
    def __init__(self, settings: AppSettings, repository: EnterpriseRepository) -> None:
        if not settings.azure_ready:
            raise AzureServiceError("Azure AI services are not fully configured")
        self._settings = settings
        self._repository = repository
        credentials = AzureCredentialHeaders(settings)
        self._parser = AzureDocumentParser(settings, credentials)
        self._models = AzureOpenAIModels(settings, credentials)
        self._search = AzureHybridSearch(settings, credentials)
        self._blobs = AzureBlobStore(settings, credentials)
        self._search.ensure_index()

    def ingest(self, principal: UserPrincipal, upload: ValidatedUpload) -> DocumentRecord:
        require_permission(principal, "knowledge:write")
        started = time.monotonic()
        record = self._repository.register_document(principal, upload)
        try:
            self._blobs.put(principal.tenant_id, upload)
            self._blobs.wait_until_clean(principal.tenant_id, upload.document_id)
            pages = self._parser.parse_pdf(upload.content)
            raw_chunks = chunk_pages(
                pages,
                tenant_id=principal.tenant_id,
                document_id=upload.document_id,
                display_name=upload.display_name,
            )
            if not raw_chunks:
                raise AzureServiceError("Document contains no indexable text")
            vectors = self._models.embeddings([item[3] for item in raw_chunks])
            chunks = tuple(
                SearchChunk(
                    chunk_id=item[0],
                    tenant_id=principal.tenant_id,
                    document_id=upload.document_id,
                    display_name=upload.display_name,
                    page=item[1],
                    section=item[2],
                    content=item[3],
                    content_vector=vectors[index],
                )
                for index, item in enumerate(raw_chunks)
            )
            self._search.upload(chunks)
            self._repository.mark_document_indexed(principal, upload.document_id, len(pages))
            self._repository.emit_audit(
                principal,
                action="knowledge.document.indexed",
                outcome=AuditOutcome.SUCCESS,
                resource_type="document",
                resource_id=upload.document_id,
                metadata={
                    "page_count": len(pages),
                    "document_count": 1,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "provider": "azure",
                    "region": self._settings.azure_region,
                },
            )
            return DocumentRecord(
                record.document_id,
                record.tenant_id,
                record.display_name,
                record.sha256,
                "ready",
                len(pages),
                record.created_at,
                record.retention_until,
            )
        except Exception:
            cleanup_completed = True
            try:
                self._search.delete_document(principal.tenant_id, upload.document_id)
                self._blobs.delete(principal.tenant_id, upload.document_id)
            except Exception:
                cleanup_completed = False
            finally:
                self._repository.mark_document_failed(principal, upload.document_id)
            self._repository.emit_audit(
                principal,
                action="knowledge.document.index_failed",
                outcome=AuditOutcome.FAILURE,
                resource_type="document",
                resource_id=upload.document_id,
                metadata={
                    "error_code": "AZURE_INGEST_FAILED",
                    "provider": "azure",
                    "reason_code": "COMPENSATED" if cleanup_completed else "RETENTION_RETRY_REQUIRED",
                },
            )
            raise

    def ask(self, principal: UserPrincipal, question: str, use_case: UseCase) -> GroundedAnswer:
        require_permission(principal, "knowledge:read")
        decision = evaluate_use_case(use_case)
        if not decision.allowed:
            self._repository.emit_audit(
                principal,
                action="knowledge.query.denied",
                outcome=AuditOutcome.DENIED,
                metadata={"reason_code": decision.reason_code, "risk_class": decision.risk_class.value},
            )
            raise PermissionError(decision.reason_code)
        cleaned = validate_question(question, self._settings.max_question_chars)
        started = time.monotonic()
        vector = self._models.embeddings([cleaned])[0]
        hits = self._search.query(principal.tenant_id, cleaned, vector)
        if not hits:
            text = "In den freigegebenen Dokumenten wurde keine belastbare Evidenz gefunden. Bitte Originalunterlagen oder einen Fachexperten hinzuziehen."
        else:
            context = "\n\n".join(
                f'<source id="S{index}" document="{hit.document_id}" page="{hit.page}">\n'
                f"{bounded_untrusted_text(hit.content)}\n</source>"
                for index, hit in enumerate(hits, start=1)
            )
            text = self._models.answer(cleaned, context)
            if not has_valid_source_citations(text, len(hits)):
                raise AzureServiceError("Model output did not pass citation validation")
        citations = tuple(
            SourceCitation(hit.document_id, hit.display_name, hit.page, hit.chunk_id, hit.score) for hit in hits
        )
        answer = GroundedAnswer.create(
            text=text,
            citations=citations,
            provenance=AIProvenance(
                provider="Microsoft Azure OpenAI",
                deployment=self._settings.azure_chat_deployment or "unknown",
                model_snapshot=self._settings.azure_model_snapshot,
                region=self._settings.azure_region or "unverified",
            ),
            use_case=use_case,
        )
        self._repository.record_answer(principal, cleaned, answer)
        self._repository.emit_audit(
            principal,
            action="knowledge.query.completed",
            outcome=AuditOutcome.SUCCESS,
            resource_type="analysis",
            resource_id=answer.answer_id,
            metadata={
                "duration_ms": int((time.monotonic() - started) * 1000),
                "source_count": len(citations),
                "provider": "azure",
                "deployment": answer.provenance.deployment,
                "model": answer.provenance.model_snapshot,
                "prompt_version": answer.provenance.prompt_version,
                "risk_class": answer.risk_class.value,
                "review_status": answer.review_status.value,
                "region": answer.provenance.region,
            },
        )
        return answer

    def delete_document(self, principal: UserPrincipal, document_id: str) -> None:
        require_permission(principal, "knowledge:write")
        self._search.delete_document(principal.tenant_id, document_id)
        self._blobs.delete(principal.tenant_id, document_id)
        self._repository.delete_document(principal, document_id)
        self._repository.emit_audit(
            principal,
            action="knowledge.document.deleted",
            outcome=AuditOutcome.SUCCESS,
            resource_type="document",
            resource_id=document_id,
            metadata={"provider": "azure"},
        )
