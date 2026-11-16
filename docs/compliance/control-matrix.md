# Compliance Control Matrix

Stand: 14. August 2026. Dies ist eine technische Kontrollzuordnung, keine Rechtsberatung, Zertifizierung oder abschließende Anwendbarkeitsprüfung.

Statusdefinitionen:

- **Implementiert**: im Repository technisch erzwungen und testbar.
- **Konfiguriert**: IaC legt den Sollzustand fest; der reale Azure-Nachweis ist zusätzlich erforderlich.
- **Externes Gate**: Vertrag, Rechtsbewertung, Organisation oder Betrieb kann nicht aus Code bewiesen werden.
- **Bedingt**: hängt von Intended Purpose, Kunde oder konkreter Instanz ab.

## DSGVO

Die Grundsätze Zweckbindung, Datenminimierung, Speicherbegrenzung, Integrität und Rechenschaftspflicht sind in Art. 5 verankert; Privacy by Design in Art. 25. Primärquellen: [DSGVO](https://eur-lex.europa.eu/eli/reg/2016/679/oj) und [EDPB Guidelines 4/2019](https://www.edpb.europa.eu/documents/guideline/guidelines-42019-article-25-data-protection-design-and-default-version_en).

| Kontrolle | Status | Technische Evidenz | Restnachweis |
| --- | --- | --- | --- |
| Datenminimierung | Implementiert | keine Rohfragen in Logs; Fragewortlaut in der Datenbank nur während einer offenen Prüfung durch eine zweite Person; pseudonymisierte Akteure/Ressourcen; Metadaten-Allowlist | Felder im VVT und je Connector prüfen |
| Privacy by Default | Implementiert | AI lokal standardmäßig aus; Produktion fail-closed; private Container; kein Tracking | Tenant-Konfiguration abnehmen |
| Zugriff/Rollen | Implementiert/konfiguriert | Entra App-Rollen, Berechtigungsprüfung, Idle Timeout, Easy Auth | Conditional Access, Joiner/Mover/Leaver, Break-glass |
| Tenant-Isolation | Implementiert | PostgreSQL FORCE RLS einschließlich `tenants`; serverseitiger Azure-Search-Tenantfilter; getrennte Web-/Lifecycle-Rollen | Integrationstest gegen reale Azure-Instanz |
| Verschlüsselung | Konfiguriert | TLS, Azure at rest, Infrastructure Encryption, private Endpunkte | Key-Lifecycle; CMK nur falls Risikoanalyse es verlangt |
| Speicherbegrenzung | Implementiert | `retention_until`; genehmigungspflichtige Policy-ID; täglicher Propagationsjob; Legal Hold je Datenklasse mit Wiedervorlage, der den Löschlauf in der Datenbankfunktion aussetzt | fachlich/rechtlich genehmigte Fristen, Backup-Löschkonzept |
| Betroffenenrechte | Teilimplementiert | subjektbezogener Export aller Felder mit Personenbezug außer Sicherheitsprotokoll (per Test gegen das Inventar geprüft), pseudonymisierte DSR-Warteschlange mit Bearbeitungsworkflow für Admins (begründete Entscheidung, Vorgangsnummer, Vier-Augen-Regel, Fristmahnung), interne 28-Tage-Zielfrist | Identitätsprüfung organisatorisch festlegen, Berichtigung/Löschung operativ umsetzen |
| Mitbestimmung (§ 87 Abs. 1 Nr. 6 BetrVG) | Technisch implementiert + extern | [Technische Anlage](works-council-annex.md) aus `hydraulikdoc/personal_data.py`; CI-Gate gegen neue Personen-Spalten im Schema; Kennzahlen nur je Anlage, KI-Qualität nur je Version und Dokument; Übersicht für Beschäftigte in der Governance-Seite | Betriebsvereinbarung bzw. Beteiligung des Betriebsrats je Standort |
| Auftragsverarbeitung | Externes Gate | Providerliste technisch Azure-only | AVV/DPA nach Art. 28, Unterauftragsverarbeiter, Weisungen |
| Drittlandtransfer | Externes Gate | regionale Standard-Deployments, private Endpunkte, Datenminimierung | TIA, SCC/DPF-Bewertung, FISA/EO/CLOUD-Act, Abuse Monitoring |
| DSFA | Bedingt/extern | Risikogates und Datenfluss dokumentiert | Art.-35-Schwellenprüfung, DSB-Freigabe, ggf. DSFA |
| TOM/Nachweis | Implementiert + extern | Audit-Hashkette mit nächtlicher Verifikation je Mandant und Ankern außerhalb der Datenbank, SBOM, CI-Scans, WAF, Runbooks | Penetrationstest, Berechtigungstest, Restore-/Incident-Übung |

Ein deutscher Azure-Standort beseitigt ein Drittland-/Behördenzugriffsrisiko nicht automatisch, weil Anbieterstruktur, Remote Support, Telemetrie und rechtliche Zugriffsmöglichkeiten separat bewertet werden müssen.

## EU AI Act

Primärquelle: [Verordnung (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj).

### Einordnung

HydraulikDoc ist nach dokumentiertem Intended Purpose ein assistives System für Dokumentrecherche und Instandhaltung. Es steuert keine Maschine, trifft keine Beschäftigungsentscheidung und erteilt keine autonome Sicherheitsfreigabe. Damit ist eine Annex-III-Hochrisikokategorie nicht aus dem aktuellen Intended Purpose ableitbar. Eine Einstufung kann sich ändern, wenn das System als Sicherheitsbauteil eines regulierten Produkts eingesetzt, zur Beschäftigtenbewertung verwendet oder sein Intended Purpose erweitert wird. Diese Verwendungen sind deshalb technisch gesperrt bzw. organisatorisch releasepflichtig.

| Artikel/Thema | Status | Technische Unterstützung | Verbleibendes externes Gate |
| --- | --- | --- | --- |
| Art. 4 AI Literacy | Implementiert + extern | versionierter Pflichtnutzerhinweis | Schulungsprogramm und Kompetenznachweise |
| Art. 9 Risikomanagement | Unterstützt | Zweckklassifizierung, gesperrte Zwecke, heightened Safety Review, Incidentworkflow | instanzbezogene Risikoakte und Owner |
| Art. 10 Daten-Governance | Unterstützt | Dokumentvalidierung, Tenantgrenze, Provenienz; Dokumentenlenkung: nur von einer zweiten Person freigegebene Revisionen sind Quelle | Prüfkriterien für die Freigabe und Qualifikation der Freigebenden festlegen |
| Art. 11 Technische Dokumentation | Unterstützt | Architektur, System Card, Modell-/Prompt-/Regionsevidenz | Betreiberakte vervollständigen |
| Art. 12 Logging | Implementiert | automatische pseudonymisierte Ereignisse, HMAC-authentisierte Hashkette mit Verifikation (`ops/scripts/verify-audit-chain.py`, System-Seite für Admins), Retention | SIEM-Aufbewahrung der nächtlichen Anker genehmigen und Alarm bei `failure_count > 0` einrichten |
| Art. 13 Transparenz | Implementiert | Quellen, Einschränkungen, Provider, Deployment, Snapshot, Promptversion, Reviewstatus | instanzbezogene Nutzerinformation |
| Art. 14 Human Oversight | Implementiert | jeder Output Draft; Reviewrollen; Prüfwarteschlange für die zweite Person bei sicherheitsrelevanten und eskalierten Antworten; endgültige Entscheidung mit festem Ablehnungsgrund; nur akzeptierte Exporte; autonome Steuerung blockiert (`tests/test_review_queue.py`) | Prüferqualifikation, Arbeitsanweisung und Zielzeit für offene Prüfungen |
| Art. 15 Accuracy/Robustness/Cybersecurity | Technisch unterstützt + extern | Hybrid Retrieval, Temperature 0, Zitatgate, Prompt-Injection-Regeln, Freigabe durch eine zweite Person gegen vergiftete Quellen, WAF, Scanpipeline, Eval-Harness und verpflichtende Eval-Evidence-ID | repräsentatives Goldset, Fachreview, Red Team und freigegebene Schwellen |
| Art. 17 QMS | Externes Gate | CI, Review und Runbooks liefern Bausteine | freigegebenes QMS mit Rollen, CAPA, Lieferanten- und Änderungsprozess |
| Art. 18 Aufbewahrung | Implementiert + extern | versionierte Provenienz und Retention | gesetzlich und fachlich korrekte Dauer genehmigen |
| Art. 50 Transparenz | Implementiert | Hinweis vor erster KI-Nutzung und Kennzeichnung als KI-Entwurf | — |
| Post-Market Monitoring | Technisch implementiert + extern | Incidenterfassung; KI-Qualitätskennzahlen aus den Fachprüfungen je Prompt-/Modellversion und Dokument mit festen Signalschwellen, Hinweis im Leitstand und CSV-Export (`hydraulikdoc/ai_quality.py`) | Meldekriterien, Owner, Behördenprozess und Bewertung der Schwellen im QMS |

Ein Produktionsrelease bleibt technisch blockiert, bis eine freigegebene `AI_EVALUATION_EVIDENCE_ID` aus dem [Eval-Harness](ai-evaluation.md) vorliegt. Der externe Prozess muss mit repräsentativen Hydraulikhandbüchern Grenzwerttreue, Citation Precision, Retrieval Recall, Halluzinationen, False Positives/Negatives und Prompt-Injection-Szenarien gegen das konkrete Modell-Snapshot bewerten.

## NIS2 / deutsches Umsetzungsgesetz

Die konkrete Betroffenheit liegt beim Betreiber/Kunden. Das BSI weist auf die seit 6. Dezember 2025 geltenden Registrierungs- und Meldeprozesse hin: [BSI NIS-2-Registrierung](https://mip2.bsi.bund.de/de/info-nis2-registrierung/).

Technische Beiträge: Risiko-/Incidentworkflow, Least Privilege, MFA-/Conditional-Access-Anknüpfung, Lieferkettenscans, immutable Releases, Backup-/Restore-Runbook, WAF und Auditnachweis. Externe Gates: Betroffenheitsprüfung, Leitungsverantwortung/Schulung, 24h-/72h-/Monatsmeldungen, BCM, Lieferantenregister, Kontaktstelle und durchgeführte Übungen.

## Cyber Resilience Act

Primärquelle: [Verordnung (EU) 2024/2847](https://eur-lex.europa.eu/eli/reg/2024/2847/oj). Ob HydraulikDoc als Produkt mit digitalen Elementen bzw. Remote-Data-Processing-Lösung in Scope fällt, hängt vom Vermarktungs- und Funktionsmodell ab und ist extern zu klassifizieren.

Repository-Bausteine: SBOM, Dependency-/Container-Scanning, Security Policy, Incidentprozess, reproduzierbares IaC und immutable Digest. Externe Gates: Vulnerability-Handling-Policy, koordinierte Offenlegung, Supportzeitraum, ENISA-/CSIRT-Meldeprozess, CE-/Konformitätsdokumentation falls anwendbar.

## Data Act

Primärquelle: [Verordnung (EU) 2023/2854](https://eur-lex.europa.eu/eli/reg/2023/2854/oj). HydraulikDoc ist nicht automatisch Hersteller der angeschlossenen Hydraulikanlage. Wenn es als Dateninhaber oder verbundener Dienst betrieben wird, sind Zugangs-, Export-, Vertrags- und Geheimnisschutzpflichten gesondert zu prüfen.

Technischer Beitrag: herstellerneutrale CSV-Eingabe, JSON-Export persönlicher Daten und keine proprietäre Bindung des KI-Nachweises. Offen: vollständiger Maschinen-/Sensordatenexport, standardisierte Connector-APIs, Geschäftsgeheimnis- und Nutzerberechtigungskonzept.

## Maschinenverordnung

Primärquelle: [Verordnung (EU) 2023/1230](https://eur-lex.europa.eu/eli/reg/2023/1230/oj). HydraulikDoc ersetzt keine Herstellerbetriebsanleitung, Risikobeurteilung, CE-Unterlage oder LOTO-Vorgabe. Originaldokumente, Seiten und Revisionsstand bleiben als Quellen sichtbar; zurückgezogene Revisionen werden nicht mehr zitiert, und autonome Maschinenhandlungen sind gesperrt. Wenn HydraulikDoc künftig digitale Herstelleranleitungen ausliefert, müssen Downloadbarkeit, Druckbarkeit, Offline-Verfügbarkeit, Lebensdauer und Papierbereitstellung separat umgesetzt und nachgewiesen werden.

## Dokumentenlenkung (ISO 9001 / IATF 16949)

Maßstab sind die Anforderungen an die Lenkung dokumentierter Information in ISO 9001 Abschnitt 7.5.3 und an technische Vorgaben in IATF 16949 Abschnitt 7.5.3.2. Die Zuordnung beschreibt, was die Anwendung technisch erzwingt; sie ist keine Konformitätsaussage und ersetzt weder das Dokumentenmanagement noch das QMS des Betreibers.

| Kontrolle | Status | Technische Evidenz | Restnachweis |
| --- | --- | --- | --- |
| Freigabe vor Verwendung | Implementiert | Upload ist Entwurf; `release_document` verlangt `document:release`, abgeschlossene Indexierung und eine andere Person als die hochladende; Suche und Zitat nur über freigegebene Dokumente (`tests/test_document_control.py`, `tests/test_postgres_integration.py`) | Prüfkriterien und Qualifikation der Freigebenden im QMS |
| Revisionsstand erkennbar | Implementiert | Revision und Dokumentnummer je Dokument, Revision im Zitat jeder Antwort | Nummernkreis und Revisionsschema des Betreibers |
| Ungültige Dokumente gegen Verwendung gesichert | Implementiert | Rückzug mit Grund ist endgültig; Freigabe einer neuen Revision zieht die Vorgängerin in derselben Transaktion zurück; gespeicherte Antworten mit zurückgezogener Quelle werden gekennzeichnet | Umgang mit bereits exportierten Nachweisen und Papierkopien |
| Regelmäßige Überprüfung | Implementiert + extern | Pflicht-Überprüfungstermin innerhalb eines Jahres, Mahnung im Leitstand, Bestätigung als Ereignis | Überprüfungsintervall je Dokumentart festlegen; überfällige Termine sperren die Quelle nicht |
| Änderungsnachweis | Implementiert | `document_events` nur einfügbar, Auditereignisse in der Hashkette | Verlauf endet mit der Löschung des Dokuments; Aufbewahrung über das Auditprotokoll |
| Verteilung und Kenntnisnahme | Externes Gate | – | Verteiler, Schulung und Kenntnisnahme neuer Revisionen |

## Betriebsgrenzen je Anlage

Grenzwerte für Condition Monitoring und Fluidbewertung sind fachliche Vorgaben des Betreibers. Die Anwendung erzwingt, dass eine verwendete Fassung eine Quelle nennt und von einer zweiten Person freigegeben wurde; ob die Werte zur Anlage passen, bleibt die Verantwortung der Freigebenden.

| Kontrolle | Status | Technische Evidenz | Restnachweis |
| --- | --- | --- | --- |
| Freigabe vor Verwendung | Implementiert | Vorschlag ist Entwurf; `release_operating_limits` verlangt `limits:release` und eine andere Person als die vorschlagende; Bewertungen verwenden nur die freigegebene Fassung (`tests/test_operating_limits.py`, `tests/test_postgres_integration.py`) | Qualifikation der Freigebenden; Prüfkriterien je Anlagentyp |
| Eindeutig gültige Fassung | Implementiert | Je Asset höchstens eine freigegebene Fassung und ein offener Vorschlag (eindeutige Teilindizes); Ablösung in derselben Transaktion | – |
| Unveränderlichkeit | Implementiert | Runtime-Rolle darf nur Statusspalten von `operating_limits` ändern und nichts löschen | Datenbankadministration nach Berechtigungskonzept |
| Rückverfolgbarkeit | Implementiert | Version, Quelle und Freigabedatum in Bewertung, Auditereignis und Incident; Auditereignisse in der Hashkette | Messwerte selbst werden nicht gespeichert |
| Quellenänderung erkannt | Implementiert | Rückzug oder Ablösung des verknüpften Dokuments markiert die Fassung im Leitstand und sperrt die Freigabe offener Vorschläge | Abgleich mit Herstellermitteilungen außerhalb der Wissensbasis |
| Ad-hoc-Grenzen | Bewusst zugelassen | Ohne freigegebene Fassung bleibt die Eingabe für eine einzelne Prüfung mit Bestätigung möglich und wird im Incident als „nicht freigegeben“ vermerkt | Betreiber entscheidet, ob Ad-hoc-Prüfungen zulässig sind |

## Barrierefreiheit

Maßstab ist WCAG 2.2 Stufe AA, wie sie EN 301 549 und BITV 2.0 referenzieren. Ob das Barrierefreiheitsstärkungsgesetz für ein B2B-Instandhaltungswerkzeug greift, hängt von Vermarktung und Kundenkreis ab; öffentliche Auftraggeber und Konzerneinkauf fordern die Konformität regelmäßig vertraglich.

| Kontrolle | Status | Technische Evidenz | Restnachweis |
| --- | --- | --- | --- |
| Kontrast Text und Status (SC 1.4.3, 1.4.11) | Implementiert | `tests/test_accessibility.py` liest die Farbwerte aus `styles.css` und prüft alle Text-/Hintergrundpaare auf 4,5:1 sowie den Fokusrahmen auf 3:1 | Kontrast der Streamlit-eigenen Komponenten im Zielbrowser messen |
| Status nicht nur über Farbe (SC 1.4.1) | Implementiert | Statuspillen, Hinweise und Checkliste tragen immer Text | – |
| Sprache der Seite (SC 3.1.1) | Teilimplementiert | Image-Build setzt `<html lang="de">` und bricht bei geänderter Streamlit-Struktur ab | in der englischen Oberfläche bleibt das Dokument technisch `de`, weil Streamlit die Sprache zur Laufzeit nicht ohne JavaScript umstellen lässt; Abhilfe: englischsprachige Instanz mit `set-document-language.py en` im Build |
| Überschriftenstruktur (SC 1.3.1, 2.4.6) | Implementiert | genau eine h1 je Arbeitsbereich, per Test geprüft | – |
| Fokus sichtbar, Bewegung reduzierbar (SC 2.4.7, 2.3.3) | Implementiert | globaler `:focus-visible`-Rahmen, `prefers-reduced-motion` | – |
| Zielgröße (SC 2.5.8) | Implementiert | Buttons mindestens 44 px hoch | – |
| Tastatur- und Screenreader-Bedienung der Kernabläufe | Externes Gate | Streamlit-Standardsteuerelemente mit zugänglichem Namen | manueller Test mit NVDA/VoiceOver, Prüfbericht nach BITV-/WCAG-Prüfverfahren |

## Releaseentscheidung

Code kann nur den technischen Zustand `configured` erreichen. Eine Kundeninstanz wird erst freigegeben, wenn die externen Gates eine signierte Evidence-ID besitzen, der reale Azure-Zustand exportiert wurde und die Nachweise mit Modell-, Image- und Infrastrukturversion verknüpft sind.
