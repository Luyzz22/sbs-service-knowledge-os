# Phase 2 compliance gap analysis

Status: initiated on 23 July 2026. This is a technical control analysis, not a
legal opinion. Retention periods, legal bases, processor terms, and the final
AI Act classification require approval by the controller's legal or data
protection function before production use.

## Regulatory baseline

- GDPR processing must be lawful, purpose-bound, data-minimised, storage-limited,
  secure, and demonstrably accountable. The European Commission summarises these
  Article 5 principles in its
  [official GDPR guidance](https://commission.europa.eu/law/law-topic/data-protection/rules-business-and-organisations/principles-gdpr/overview-principles/what-data-can-we-process-and-under-which-conditions_en).
- Individuals must receive clear information about purposes, categories, legal
  basis, retention, recipients, rights, and automated decision-making. See the
  Commission's [controller obligations guidance](https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/obligations_en).
- Erasure must cover the controller's systems and, where applicable, propagation
  to recipients, subject to the GDPR exceptions. See the Commission's
  [right-to-erasure guidance](https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/dealing-requests-individuals/do-we-always-have-delete-personal-data-if-person-asks_en).
- Data protection controls must be designed in and privacy-friendly by default.
  See the EDPB's final
  [Guidelines 4/2019](https://www.edpb.europa.eu/documents/guideline/guidelines-42019-on-article-25-data-protection-by-design-and-by-default_en).
- AI Act Article 50 transparency duties apply from 2 August 2026. A person
  interacting with an AI system must be informed clearly by the first
  interaction. See the
  [AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/) and the Commission's
  [Article 50 FAQ](https://digital-strategy.ec.europa.eu/en/faqs/transparency-obligations-under-article-50-ai-act).

## Current data flow

1. A username and password are checked against Streamlit secrets or built-in
   demo records.
2. Uploaded PDFs are written to a temporary file and transferred to LlamaParse.
3. Parsed document text, original filename, page number, upload time, and
   username are retained in Streamlit session memory.
4. Document chunks are sent to OpenAI for embeddings and answers. The current
   Qdrant client is in-memory even though Phase 1 supplies a persistent service.
5. User questions and selected document context are sent to OpenAI. The complete
   question is also written to application logs.
6. Video, audio, and a PDF manual are copied into a temporary directory and sent
   inline to Google Vertex AI. The temporary directory is removed on exit.
7. Document removal rebuilds the in-memory index, but no downstream erasure or
   data-subject-request evidence is recorded.

## Gap and release-gate register

| Priority | Finding | Evidence | Required control |
| --- | --- | --- | --- |
| Blocker | Production authentication can fall back to public MD5 demo passwords. | `app.py` `AuthManager` | Disable fallback in production; use a memory-hard password verifier or an external identity provider; add throttling and session expiry. |
| Blocker | Processor and transfer configuration is not evidenced. | LlamaParse, OpenAI, and Vertex AI calls | Record controller/processor roles, DPA versions, sub-processors, regions, transfer mechanism, and per-tenant feature enablement before production. |
| High | Raw user questions are logged. | `app.py` `query_knowledge_base` | Replace content logging with pseudonymous event IDs, outcome, timing, model, and counts. |
| High | Uploaded content carries filename and username into document metadata. | `app.py` `parse_pdf_with_llamaparse` | Use internal opaque IDs; keep identifying metadata in a separately protected mapping only where necessary. |
| High | No versioned privacy/contract acceptance exists. | No persistence model | Store immutable document version, digest, subject token, timestamp, purpose, and evidence; require re-acceptance when the relevant version changes. |
| High | Erasure is session-local and does not evidence processor propagation. | `app.py` `remove_document` | Add data inventory, data-subject-request state machine, processor deletion adapters, completion evidence, and exception codes. |
| High | AI output is injected as unsafe HTML. | `streamlit_integration.py` result rendering | Render as text/Markdown with unsafe HTML disabled and sanitise any allowed rich content. |
| High | AI disclosure is incomplete and the existing GDPR statement asserts compliance without runtime evidence. | `streamlit_integration.py` | Show provider, purpose, limitations, human-review requirement, and data handling before the first interaction; replace absolute compliance claims with factual configuration. |
| Medium | Retention periods and expiry jobs are absent. | No retention policy | Approve a processing-register-backed policy, attach `expires_at`, and run deletion/anonymisation jobs with evidence. |
| Medium | Audit logs are not separated from diagnostic logs. | `EnterpriseLogger` | Emit append-oriented, pseudonymised compliance events with strict metadata allowlists and bounded retention. |
| Medium | Operational persistence and application persistence disagree. | Qdrant Compose service versus `QdrantClient(\":memory:\")` | Introduce tenant-scoped collections and repositories before storing production documents. |

## Controls started in this branch

- `compliance.audit` creates stable HMAC-based tokens so audit evidence does not
  contain raw usernames, email addresses, filenames, prompts, or document IDs.
- Audit metadata is deny-by-default: only bounded technical fields are retained.
- `compliance.retention` centralises timezone-safe expiry calculation and
  environment configuration.
- Tests prove identifier non-disclosure, metadata minimisation, and retention
  calculations.

The operational defaults are placeholders, not approved legal retention
periods. Production must fail closed until the controller has mapped each record
class to a purpose, legal basis, owner, recipient set, and approved period.

## Phase 2 implementation order

1. Replace insecure authentication and add production fail-closed configuration.
2. Add PostgreSQL repositories for users, legal-document versions, acceptances,
   audit events, AI interaction evidence, and data-subject requests.
3. Integrate pseudonymous audit events while removing raw question and filename
   logs.
4. Add first-interaction AI disclosure and versioned privacy/contract acceptance.
5. Implement end-to-end access/export/erasure with processor propagation.
6. Enforce retention and anonymisation jobs, then run a deletion verification
   test across PostgreSQL, Qdrant, backups, and configured processors.
