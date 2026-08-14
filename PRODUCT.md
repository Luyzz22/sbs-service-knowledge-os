# HydraulikDoc Enterprise Product Definition

Status: Implementierungsbaseline 5.0, 14. August 2026

## Zielbild

HydraulikDoc ist die evidenzorientierte Arbeitsoberfläche zwischen technischer Dokumentation, Zustandsdaten und Instandhaltungsentscheidung. Der Differenzierungsfaktor ist nicht ein allgemeiner Chatbot, sondern eine kontrollierte Beweiskette: Tenant, Asset, Originalquelle, Seite, Modell-/Promptversion, Risikoklasse und Human Review bleiben zusammen nachvollziehbar.

## Primäre Nutzer

- Servicetechniker recherchieren Grenzwerte, prüfen Messreihen und dokumentieren Auffälligkeiten.
- Instandhaltungsleiter verwalten Assets, prüfen KI-Entwürfe und exportieren freigegebene Evidenz.
- Reliability- und Fluid-Spezialisten vergleichen Zustands- und Ölindikatoren mit anlagenbezogenen Betriebsgrenzen.
- Informationssicherheit, Datenschutz und Qualitätsmanagement prüfen Rollen, Regionen, Löschfristen, Modellprovenienz und Auditereignisse.
- IT-Betrieb verwaltet eine Azure-Instanz über IaC, OIDC, Managed Identity, private Endpunkte und standardisierte Runbooks.

## Kernabläufe

1. Ein berechtigter Nutzer registriert ein Asset mit Standort und Kritikalität.
2. Ein technisches PDF wird validiert, privat gespeichert, auf Malware geprüft, strukturiert extrahiert und tenant-isoliert indexiert.
3. Eine Frage wird klassifiziert. Gesperrte Zwecke werden vor jedem Modellaufruf abgewiesen.
4. Hybrid Retrieval liefert tenant-gefilterte Evidenz. Das Modell darf ausschließlich diese Evidenz verwenden.
5. Ein Output ohne gültige `[S1]`-Quellenmarke wird verworfen und nicht persistiert.
6. Der Entwurf wird mit Modell-, Deployment-, Region-, Prompt-, Zeit-, Nutzer- und Quellenprovenienz gespeichert.
7. Ein berechtigter Mensch akzeptiert, verwirft oder eskaliert. Nur akzeptierte Ergebnisse sind exportierbar.
8. Dokumentlöschung und Fristablauf werden über Blob, AI Search und PostgreSQL propagiert und auditiert.

## Capability Contract

| Status | Fähigkeit | Evidenz |
| --- | --- | --- |
| Implementiert | Entra-App-Rollen, Tenant-Filter und PostgreSQL FORCE RLS mit getrennter Lifecycle-Rolle | `hydraulikdoc/auth.py`, `db/migrations/001_enterprise.sql` |
| Implementiert | Azure-only RAG mit Managed Identity | `hydraulikdoc/azure_ai.py`, `infra/azure/main.bicep` |
| Implementiert | Uploadvalidierung, Malware-Gate und private Speicherung | `hydraulikdoc/security.py`, `hydraulikdoc/azure_ai.py` |
| Implementiert | KI-Zitatvalidierung und Prompt-Injection-Abwehr | `hydraulikdoc/governance.py`, `hydraulikdoc/azure_ai.py` |
| Implementiert | Human Review und rollenbegrenzter Export | `hydraulikdoc/ui.py`, `hydraulikdoc/repository.py` |
| Implementiert | Deterministische Condition-/Fluid-Vorbewertung | `hydraulikdoc/condition_monitoring.py`, `fluid_advisor.py` |
| Implementiert | Datenschutz-Self-Service und DSR-Warteschlange | `hydraulikdoc/ui.py`, `privacy_requests` |
| Implementiert in IaC | Auswahl deutscher Azure-Regionen, private PaaS-Endpunkte, WAF, Zonenredundanz | `infra/azure/main.bicep`; reale Konfiguration ist Deployment-Evidenz |
| Externes Gate | AVV/DPA, Transferbewertung, DSFA, Rechtsgrundlagen, Betriebsrat | kundeninstanzbezogene Evidenz außerhalb des Codes |
| Externes Gate | ISO-/C5-Testat, Pentest, Restore-Nachweis, SLA | nur nach abgeschlossenem Prüfverfahren kommunizieren |

## Bewusste Grenzen

- Keine autonome Maschinensteuerung, Safety-PLC-Anbindung oder Fernabschaltung.
- Keine Beschäftigtenleistungsbewertung oder verdeckte Nutzeranalyse.
- Keine automatisierte CE-, Konformitäts- oder Rechtsfreigabe.
- Keine automatische Übernahme generischer Grenzwerte als Herstellerfreigabe.
- Kein Video-/Audio-Upload im Produktionsumfang, bis ein gleichwertiger Malware-, Datenschutz- und Reviewpfad implementiert ist.
- Keine absolute Compliance-, Residenz- oder Zertifizierungsbehauptung ohne instanzbezogenen Nachweis.

## Experience Brief

Die Oberfläche wirkt wie ein industrieller Leitstand und nicht wie eine Consumer-KI: klare Hierarchie, helle Arbeitsfläche, dunkelblaue Navigation, kupferfarbene Primäraktion, kompakte Evidenztabellen und sichtbare Releasezustände. Kritische Hinweise verwenden Text und Struktur zusätzlich zu Farbe.

### Design-Dials

- Dichte: mittel; große Übersicht, kompakte Fachdatentabellen.
- Ton: präzise, deutsch, handlungsorientiert, ohne Marketing-Superlative.
- Typografie: Systemschrift, tabellarische Daten gut scannbar, genau eine dominante H1.
- Bewegung: keine dekorative Animation; Reduced Motion wird respektiert.
- Vertrauen: technische Evidenz, konfigurierte Kontrollen und externe Gates werden getrennt dargestellt.
- Responsive: vollständige Bedienbarkeit ab 360 px; Tabellen dürfen scrollen, Kernaktionen bleiben sichtbar.

## Erfolgsmetriken

Metriken sind Zielgrößen und werden erst nach Telemetrie- und Datenschutzfreigabe erhoben:

- Anteil der KI-Entwürfe mit gültiger Quelle: technisch 100 %, da fehlende Zitate blockieren.
- Anteil exportierter Ergebnisse mit akzeptiertem Review: technisch 100 %.
- Zeit bis zur qualifizierten Quelle und Zeit bis zum Incident.
- Retrieval-Recall, fachliche Akzeptanz, False-Positive-/False-Negative-Rate je freigegebener Eval-Suite.
- Löschpropagation ohne Fehler und quartalsweise bestandene Restore-Drills.

## Releasekriterien

Ein Kundenrelease ist erst zulässig, wenn Code-Gates grün sind, das immutable Image per Digest referenziert ist, Entra-Rollen zugewiesen wurden, Modell und Region verfügbar sind, AI-Evaluation, Retention und Compliance jeweils freigegebene Evidence-IDs besitzen, das öffentliche Zertifikat installiert ist und die organisatorischen Gates der Kontrollmatrix als Evidenz hinterlegt wurden.
