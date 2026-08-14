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
| Datenminimierung | Implementiert | keine Rohfragen in Logs; pseudonymisierte Akteure/Ressourcen; Metadaten-Allowlist | Felder im VVT und je Connector prüfen |
| Privacy by Default | Implementiert | AI lokal standardmäßig aus; Produktion fail-closed; private Container; kein Tracking | Tenant-Konfiguration abnehmen |
| Zugriff/Rollen | Implementiert/konfiguriert | Entra App-Rollen, Berechtigungsprüfung, Idle Timeout, Easy Auth | Conditional Access, Joiner/Mover/Leaver, Break-glass |
| Tenant-Isolation | Implementiert | PostgreSQL FORCE RLS einschließlich `tenants`; serverseitiger Azure-Search-Tenantfilter; getrennte Web-/Lifecycle-Rollen | Integrationstest gegen reale Azure-Instanz |
| Verschlüsselung | Konfiguriert | TLS, Azure at rest, Infrastructure Encryption, private Endpunkte | Key-Lifecycle; CMK nur falls Risikoanalyse es verlangt |
| Speicherbegrenzung | Implementiert | `retention_until`; genehmigungspflichtige Policy-ID; täglicher Propagationsjob | fachlich/rechtlich genehmigte Fristen, Backup-Löschkonzept |
| Betroffenenrechte | Teilimplementiert | subjektbezogener Export, pseudonymisierte DSR-Warteschlange, interne 28-Tage-Zielfrist | Identitäts-/Ausnahmeprüfung, Berichtigung/Löschung operativ abschließen |
| Auftragsverarbeitung | Externes Gate | Providerliste technisch Azure-only | AVV/DPA nach Art. 28, Unterauftragsverarbeiter, Weisungen |
| Drittlandtransfer | Externes Gate | regionale Standard-Deployments, private Endpunkte, Datenminimierung | TIA, SCC/DPF-Bewertung, FISA/EO/CLOUD-Act, Abuse Monitoring |
| DSFA | Bedingt/extern | Risikogates und Datenfluss dokumentiert | Art.-35-Schwellenprüfung, DSB-Freigabe, ggf. DSFA |
| TOM/Nachweis | Implementiert + extern | Audit-Hashkette, SBOM, CI-Scans, WAF, Runbooks | Penetrationstest, Berechtigungstest, Restore-/Incident-Übung |

Ein deutscher Azure-Standort beseitigt ein Drittland-/Behördenzugriffsrisiko nicht automatisch, weil Anbieterstruktur, Remote Support, Telemetrie und rechtliche Zugriffsmöglichkeiten separat bewertet werden müssen.

## EU AI Act

Primärquelle: [Verordnung (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj).

### Einordnung

HydraulikDoc ist nach dokumentiertem Intended Purpose ein assistives System für Dokumentrecherche und Instandhaltung. Es steuert keine Maschine, trifft keine Beschäftigungsentscheidung und erteilt keine autonome Sicherheitsfreigabe. Damit ist eine Annex-III-Hochrisikokategorie nicht aus dem aktuellen Intended Purpose ableitbar. Eine Einstufung kann sich ändern, wenn das System als Sicherheitsbauteil eines regulierten Produkts eingesetzt, zur Beschäftigtenbewertung verwendet oder sein Intended Purpose erweitert wird. Diese Verwendungen sind deshalb technisch gesperrt bzw. organisatorisch releasepflichtig.

| Artikel/Thema | Status | Technische Unterstützung | Verbleibendes externes Gate |
| --- | --- | --- | --- |
| Art. 4 AI Literacy | Implementiert + extern | versionierter Pflichtnutzerhinweis | Schulungsprogramm und Kompetenznachweise |
| Art. 9 Risikomanagement | Unterstützt | Zweckklassifizierung, gesperrte Zwecke, heightened Safety Review, Incidentworkflow | instanzbezogene Risikoakte und Owner |
| Art. 10 Daten-Governance | Unterstützt | Dokumentvalidierung, Tenantgrenze, Provenienz | Datenqualität und Repräsentativität freigeben |
| Art. 11 Technische Dokumentation | Unterstützt | Architektur, System Card, Modell-/Prompt-/Regionsevidenz | Betreiberakte vervollständigen |
| Art. 12 Logging | Implementiert | automatische pseudonymisierte Ereignisse, HMAC-authentisierte Hashkette, Retention | SIEM-Aufbewahrung genehmigen |
| Art. 13 Transparenz | Implementiert | Quellen, Einschränkungen, Provider, Deployment, Snapshot, Promptversion, Reviewstatus | instanzbezogene Nutzerinformation |
| Art. 14 Human Oversight | Implementiert | jeder Output Draft; Reviewrollen; nur akzeptierte Exporte; autonome Steuerung blockiert | Prüferqualifikation und Arbeitsanweisung |
| Art. 15 Accuracy/Robustness/Cybersecurity | Technisch unterstützt + extern | Hybrid Retrieval, Temperature 0, Zitatgate, Prompt-Injection-Regeln, WAF, Scanpipeline, Eval-Harness und verpflichtende Eval-Evidence-ID | repräsentatives Goldset, Fachreview, Red Team und freigegebene Schwellen |
| Art. 17 QMS | Externes Gate | CI, Review und Runbooks liefern Bausteine | freigegebenes QMS mit Rollen, CAPA, Lieferanten- und Änderungsprozess |
| Art. 18 Aufbewahrung | Implementiert + extern | versionierte Provenienz und Retention | gesetzlich und fachlich korrekte Dauer genehmigen |
| Art. 50 Transparenz | Implementiert | Hinweis vor erster KI-Nutzung und Kennzeichnung als KI-Entwurf | — |
| Post-Market Monitoring | Teilimplementiert | Incidenterfassung, abgelehnter und Expert Review | Trendanalyse, Meldekriterien, Owner und Behördenprozess |

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

Primärquelle: [Verordnung (EU) 2023/1230](https://eur-lex.europa.eu/eli/reg/2023/1230/oj). HydraulikDoc ersetzt keine Herstellerbetriebsanleitung, Risikobeurteilung, CE-Unterlage oder LOTO-Vorgabe. Originaldokumente und Seiten bleiben als Quellen sichtbar; autonome Maschinenhandlungen sind gesperrt. Wenn HydraulikDoc künftig digitale Herstelleranleitungen ausliefert, müssen Downloadbarkeit, Druckbarkeit, Offline-Verfügbarkeit, Lebensdauer und Papierbereitstellung separat umgesetzt und nachgewiesen werden.

## Releaseentscheidung

Code kann nur den technischen Zustand `configured` erreichen. Eine Kundeninstanz wird erst freigegeben, wenn die externen Gates eine signierte Evidence-ID besitzen, der reale Azure-Zustand exportiert wurde und die Nachweise mit Modell-, Image- und Infrastrukturversion verknüpft sind.
