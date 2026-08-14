# Security Policy

## Supported versions

Security fixes are provided for the current `main` revision and the currently operated immutable production digest. Demo, legacy and unmerged branches are not supported production releases.

## Reporting a vulnerability

Do not disclose a suspected vulnerability, credential, customer name, document or tenant identifier in a public issue. Use the repository's private GitHub Security Advisory channel or the confidential incident channel named in the applicable customer/support agreement.

Include only the minimum evidence needed:

- affected commit or image digest;
- impact and prerequisites;
- safe reproduction steps;
- pseudonymised request/correlation IDs;
- suggested mitigation, if known.

Never attach production documents, tokens, database dumps, Entra headers or Key-Vault values. The response team will acknowledge through the same confidential channel, assign severity and coordinate disclosure. A fixed response time is not promised by this repository; contractual SLAs prevail.

## Security boundaries

- Production requires Entra proxy authentication, Azure AI, PostgreSQL, Managed Identity, an approved German region, Human Review, compliance evidence, AI-evaluation evidence and a versioned retention policy.
- Local authentication is development-only and requires Argon2id hashes supplied outside Git.
- The application never accepts an arbitrary tenant identifier from a form or query parameter. Tenant context originates from the verified Entra principal.
- Tenant metadata is protected by FORCE RLS. The web runtime cannot invoke retention deletion; a separate lifecycle database role has only the bounded enumeration, document-update, audit and purge rights required by the scheduled job.
- Azure service keys are forbidden in production. Database and HMAC secrets are Key-Vault references.
- Autonomous machine control and employee monitoring are explicitly out of scope and technically blocked.

## Coordinated response

The incident commander follows [Incident Response](docs/runbooks/incident-response.md). Security fixes must pass the complete CI gate, update the System Card or threat model when behavior changes, and be deployed by immutable digest. Credential exposure additionally requires rotation and an audit of downstream access; deleting a Git commit is not sufficient remediation.

## Safe harbour

Good-faith testing must stay within an explicitly authorised non-production tenant, avoid persistence or lateral movement, stop after proof of impact, and respect privacy and availability. This document does not grant permission to test customer or production systems.
