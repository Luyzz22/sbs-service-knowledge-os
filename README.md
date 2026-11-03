# HydraulikDoc Enterprise

HydraulikDoc ist ein mandantenfähiger Arbeitsraum für industrielle Instandhaltung. Die Anwendung verbindet Anlagenregister, technische PDF-Dokumentation, quellengebundene KI-Entwürfe, deterministische Zustandsbewertung, Fluidbewertung, Incidents und prüfbare Human-Review-Nachweise.

Der Produktionspfad ist bewusst auf Microsoft Azure begrenzt. Google Gemini, LlamaCloud und Qdrant gehören nicht mehr zum Runtime- oder Containerpfad.

## Produktgrenzen

- HydraulikDoc unterstützt Fachkräfte; es steuert keine Maschine.
- Autonome Maschinensteuerung und Beschäftigtenüberwachung sind technisch gesperrt.
- Jeder KI-Entwurf bleibt `draft`, bis eine berechtigte Person ihn akzeptiert, ablehnt oder einen Experten anfordert.
- Nur akzeptierte Ergebnisse können durch Rollen mit `analysis:export` als Nachweis exportiert werden.
- Aussagen wie „DSGVO-konform“, „zertifiziert“ oder „kein Drittlandrisiko“ werden nicht aus Code abgeleitet. Verträge, DSFA/TIA, Betriebsrat, Rechtsgrundlage, Löschkonzept und Betriebsnachweise bleiben Release-Gates.

## Produktionsarchitektur

| Ebene | Implementierung |
| --- | --- |
| Edge | Azure Application Gateway WAF v2, TLS, Rate Limit, OWASP-/Bot-Regeln |
| Identität | Microsoft Entra ID / Container Apps Easy Auth, App-Rollen, 30-Minuten-Idle-Timeout |
| Compute | Azure Container Apps, mindestens zwei Replikate, Managed Identity, Read-only Container |
| Dokumente | Private Azure Blob Storage, Defender for Storage On-upload Malware Scanning |
| Extraktion | Azure AI Document Intelligence `prebuilt-layout` |
| Retrieval | Azure AI Search, Hybrid- und Vektorsuche, verpflichtender Tenant-Filter |
| Generierung | Azure OpenAI Deployment, Temperature 0, versionierter Prompt, Zitatvalidierung |
| Fachdaten | Azure Database for PostgreSQL Flexible Server, private Netzwerkanbindung, FORCE RLS einschließlich Tenant-Stammdaten |
| Secrets | Azure Key Vault und Managed Identity; statische Azure-Service-Keys sind in Produktion verboten |
| Lifecycle | Täglicher Azure Container Apps Job mit separater DB-Rolle löscht abgelaufene Daten aus Search, Blob und PostgreSQL |
| Lieferkette | GitHub OIDC, Bicep, immutable Image Digest, SBOM, Ruff, mypy, Bandit, pip-audit und Trivy |

Details: [Azure-Zielarchitektur](docs/architecture/azure-enterprise.md), [Kontrollmatrix](docs/compliance/control-matrix.md), [Marktscan](docs/market/market-scan-de-hydraulics-2026.md).

## Lokal starten

Voraussetzungen: Python 3.11 und eine virtuelle Umgebung.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock
cp .env.example .env
python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('ein-langes-lokales-passwort'))"
```

Den Hash in eine nicht versionierte Datei `secrets/local_users_json` eintragen:

```json
{
  "entwickler": {
    "password_hash": "$argon2id$...",
    "role": "admin",
    "display_name": "Lokale Entwicklung"
  }
}
```

Ein mindestens 32 Byte langes zufälliges HMAC-Geheimnis in `secrets/audit_hmac_key` ablegen. Danach die Variablen laden und starten:

```bash
set -a
source .env
set +a
streamlit run app.py
```

Das Container-Image setzt die Dokumentsprache auf Deutsch (WCAG 3.1.1). Lokal lässt sich das mit `python ops/scripts/set-document-language.py de` nachstellen.

Der lokale Default hat `AI_BACKEND=disabled` und `PERSISTENCE_BACKEND=memory`. Er sendet keine Dokumente an externe KI-Dienste.

### Sprache

Die Oberfläche ist auf Deutsch und Englisch verfügbar. Beim ersten Aufruf folgt sie der Browser-Einstellung (`Accept-Language`), sonst gilt `DEFAULT_LANGUAGE` (`de` oder `en`). Umschalten lässt sich jederzeit über „Sprache · Language“ in der Seitenleiste oder auf der Anmeldeseite; die Wahl gilt für die Sitzung und wird nicht personenbezogen gespeichert. Gespeicherte Fachdaten (Incident-Titel, 8D-Texte, Dokumente) bleiben in der Sprache, in der sie erfasst wurden. Der KI-Nutzerhinweis und der Datenschutzhinweis liegen in beiden Sprachen vor; die Bestätigung speichert den Hash genau der angezeigten Fassung.

Neue Oberflächentexte werden auf Deutsch mit `tr()` oder `msg()` geschrieben und in `hydraulikdoc/translations.py` übersetzt. `tests/test_i18n.py` schlägt fehl, wenn eine Übersetzung fehlt, Platzhalter abweichen oder Einträge verwaist sind.

### Demo-Mandant für Vorführungen

Für Vertriebs- und Schulungsdemos ohne Azure und ohne Kundendaten zusätzlich `AI_BACKEND=demo` setzen:

```bash
AI_BACKEND=demo streamlit run app.py
```

Als Supervisor oder Admin anmelden und im Leitstand **Demodaten laden** wählen. Geladen werden vier fiktive Anlagen mit SAP-Referenzen, zwei synthetische Handbücher und vier Incidents in den Zuständen „neu und kritisch“, „8D in Bearbeitung“, „wartet auf Abnahme“ und „abgeschlossen“. Condition Monitoring bietet eine synthetische 48-h-Messreihe ohne Upload.

Der Demo-Pfad ruft kein Sprachmodell auf: Antworten bestehen aus unverändert extrahierten Sätzen der synthetischen Handbücher mit Seitenbeleg und durchlaufen dieselben Sperren, Reviews und Auditereignisse wie der Azure-Pfad. Ein Banner kennzeichnet jede Seite, alle Daten tragen das Präfix `DEMO`. `AI_BACKEND=demo` ist in Produktion und hinter Entra ID technisch gesperrt; die Demodaten werden nur in einen leeren Mandanten geladen. Empfohlene Fragen für die Vorführung:

- Welcher Betriebsdruck gilt für HA-250 und wann ist das Aggregat stillzusetzen?
- Wie hoch darf der Wassergehalt sein?
- Was ist bei hoher Partikelzahl zu tun?

## Qualitätssicherung

```bash
ruff check app.py compliance hydraulikdoc fluid_advisor.py incident_model.py tests ops/scripts
ruff format --check app.py compliance hydraulikdoc fluid_advisor.py incident_model.py tests ops/scripts
mypy hydraulikdoc compliance fluid_advisor.py incident_model.py ops/scripts/*.py
python -m unittest discover --start-directory tests --verbose
bandit -c pyproject.toml -r app.py compliance hydraulikdoc ops/scripts
pip-audit -r requirements.lock
PYTHONPATH=. python ops/scripts/run-ai-evaluation.py  # mit geschütztem Goldset und Azure-Evalprofil
az bicep build --file infra/azure/main.bicep --stdout >/dev/null
docker build -t hydraulikdoc:local .
```

## Produktionsfreigabe

Eine Azure-Auslieferung läuft nur, wenn alle drei Repository-Variablen explizit `true` sind:

- `AZURE_DEPLOY_ENABLED`
- `COMPLIANCE_RELEASE_APPROVED`
- `RETENTION_POLICY_APPROVED`

Zusätzlich müssen `RETENTION_POLICY_ID`, Modellname/-version, Hostname, Zertifikat und Entra-Anwendung evidenzbasiert hinterlegt sein. Die vollständige Abfolge steht im [Azure-Deployment-Runbook](docs/runbooks/azure-deployment.md).
Zusätzlich ist eine nicht-leere `AI_EVALUATION_EVIDENCE_ID` aus der [fachlichen AI-Evaluation](docs/compliance/ai-evaluation.md) technisch erforderlich.

## Dokumentation

- [Produktdefinition](PRODUCT.md)
- [Enterprise-Review DACH und Roadmap](docs/product/enterprise-review-2026-11.md)
- [Designsystem](DESIGN.md)
- [Security Policy](SECURITY.md)
- [AI System Card](docs/compliance/ai-system-card.md)
- [Incident Response](docs/runbooks/incident-response.md)
- [Backup und Restore](docs/runbooks/backup-restore.md)
- [Datenschutz und Retention](docs/runbooks/privacy-retention.md)

## Lizenz und Verantwortung

Vor einer Kundeninstanz müssen Lizenz, Supportmodell, AVV/DPA, Unterauftragsverarbeiter, Informationspflichten und regulatorische Verantwortlichkeiten vertraglich festgelegt werden. Dieses Repository liefert technische Kontrollen und Evidenzpunkte, keine Rechtsberatung und keine Zertifizierung.
