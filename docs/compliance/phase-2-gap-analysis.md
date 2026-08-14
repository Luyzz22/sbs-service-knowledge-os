# Phase 2 Control Closure

Stand: 14. August 2026. Das frühere Demo-Gap-Register wurde mit der Enterprise-Implementierung 5.0 technisch abgelöst.

## Geschlossene Blocker

| Früherer Befund | Umsetzung |
| --- | --- |
| MD5-Demokennwörter / öffentlicher Fallback | Produktion erzwingt Entra Easy Auth und App-Rollen; lokal ausschließlich Argon2id ohne Defaultnutzer |
| LlamaParse/OpenAI/Vertex als unkontrollierte Prozessoren | aus Runtime, Container und Requirements entfernt; Azure-only Produktionspfad mit regionalen Standarddeployments |
| Rohfragen in Logs | keine Inhaltslogs; SHA-256 nur in Fachdatenbank; Auditmetadaten-Allowlist |
| Filename/Username in Vector Metadata | Tenant stammt aus Entra; Searchfilter verpflichtend; Akteure in Auditdaten HMAC-pseudonymisiert |
| In-memory Qdrant | Azure AI Search für Retrieval und PostgreSQL mit FORCE RLS für Fachdaten |
| Session-lokale Löschung | Search-, Blob- und DB-Propagation plus täglicher Retention-Job |
| Fehlende Transparenz/Review | Nutzerhinweis, Quellen, Modell-/Promptprovenienz, Draftstatus und rollenbegrenzter Export |
| Unsafe HTML für KI-Output | Modelloutput wird als sicheres Streamlit-Markdown ohne `unsafe_allow_html` gerendert |
| Runtime-Schemarechte | Migration nur im privilegierten Bootstrap; Runtime ohne DDL/allgemeines DELETE |

## Verbleibende Release-Gates

Die offenen Punkte sind bewusst nicht als „per Code gelöst“ markiert:

- AVV/DPA, Unterauftragsverarbeiter und Transfer Impact Assessment für die konkrete Azure-Instanz;
- Rechtsgrundlagen, VVT, Informationspflichten, DSFA-Schwellenprüfung und Betriebsratsbeteiligung;
- fachliche AI-Eval-Suite für das reale Modell-Snapshot und die freigegebenen Handbuchtypen;
- Penetrationstest, Tenant-E2E-Test, WAF-/Defender-/SIEM-Integration;
- Restore-/Failoverübung und bestätigte RPO/RTO;
- Incident-, DSR-, Legal-Hold-, QMS- und Schulungsprozess mit benannten Verantwortlichen;
- abschließende AI-Act-, NIS2-, CRA-, Data-Act- und Maschinenverordnungs-Einordnung je Vermarktung/Intended Purpose.

Diese Gates sind in [Control Matrix](control-matrix.md), [Azure Deployment](../runbooks/azure-deployment.md) und [AI System Card](ai-system-card.md) konkretisiert.
