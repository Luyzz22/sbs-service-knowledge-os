# Enterprise-Review DACH: Bewertung und Roadmap

Stand: 3. November 2026, Basis Commit `596e774` (Incident-Workflow).

## Methode

Der Review betrachtet HydraulikDoc aus drei Prüfperspektiven, wie sie große DACH-Industriekunden in Einkauf, IT-Architektur und Werksbetrieb typischerweise anlegen. Die Perspektiven sind gedankliche Prüfrahmen dieses Teams; es handelt sich **nicht** um Aussagen, Audits oder Empfehlungen der genannten Unternehmenstypen.

| Perspektive | Leitfrage | Typische Prüfkriterien |
| --- | --- | --- |
| Bedienqualität (Consumer-/Premium-Hardware-Hersteller) | Erledigt ein Mensch die nächste Aufgabe ohne Schulung? | Aufgabe vor Marketing, klare nächste Handlung, Lesbarkeit, Responsive, Barrierefreiheit |
| ERP-Integration (Enterprise-Software-Anbieter) | Passt das Produkt in eine bestehende SAP-Landschaft? | Stammdatenbezug, Massenimport, Übergabeformate, Datenhoheit, Rollenmodell |
| Werksbetrieb und Qualität (Automobil-OEM) | Ist jede Entscheidung rückverfolgbar und sicher? | Traceability, Vier-Augen-Prinzip, Problemlösungsmethodik (8D), Informationssicherheit (TISAX-Erwartung), Exportsicherheit |

Bewertet wird die Erfolgswahrscheinlichkeit eines Pilotprojekts in einem DACH-Werk: Ein Pilot scheitert selten an der KI, sondern an fehlender Anbindung an SAP PM, unklarem nächsten Schritt im Alltag und Sicherheitsbefunden im Security-Review.

## Befunde

Priorität: **P1** blockiert Pilot oder Security-Freigabe, **P2** senkt Akzeptanz deutlich, **P3** Ausbau.

| ID | Perspektive | Befund | Prio | Status |
| --- | --- | --- | --- | --- |
| S1 | ERP | Assets ohne Technischen Platz (TPLNR) und Equipment (EQUNR); keine Verknüpfung zum SAP-Stammsatz | P1 | umgesetzt |
| S2 | ERP | Kein Massenimport; Hunderte Anlagen müssten einzeln erfasst werden | P1 | umgesetzt: CSV-Import (Semikolon/Komma, deutsche Kritikalitätswerte, alles-oder-nichts) |
| S3 | ERP | Kein Übergabeformat vom Incident zur Instandhaltungsmeldung | P1 | umgesetzt: SAP-PM-orientierte CSV-Übergabe (QMART, QMTXT, PRIOK, TPLNR, EQUNR), Mapping kundenseitig zu validieren |
| D3 | Werk/Sicherheit | CSV-Exporte ohne Schutz vor Formel-Injection beim Öffnen in Excel (CWE-1236) | P1 | umgesetzt für alle neuen Exporte |
| D4 | Werk/Sicherheit | Mandant, Rolle und Releasezustand wurden unescaped in HTML interpoliert | P1 | umgesetzt |
| U3 | Bedienung | Leitstand zeigte nur Zählwerte, keine nächste Handlung | P2 | umgesetzt: Handlungsbedarf (kritisch, unbestätigt, Abnahme) und Einrichtungsfortschritt mit Sprungziel |
| U1 | Bedienung | Großer Hero auf jeder Arbeitsseite verdrängt die Arbeitsfläche | P2 | umgesetzt: Hero nur im Leitstand, sonst kompakte Kontextleiste; kompakter Hero auf Tablets |
| U2 | Bedienung | Abmelden-Button weiß auf weiß und damit unlesbar | P2 | umgesetzt |
| U4 | Bedienung | Englische Rohwerte (`safety_critical`, `active`) in Fachtabellen | P2 | umgesetzt im Asset Register |
| D1 | Werk | Incidents ohne Ursache, Sofort- und Abstellmaßnahme (8D/A3) | P2 | umgesetzt: 8D-light mit Pflichtfeldern vor „Behoben“ und Abnahme |
| D2 | Werk | Statusverlauf je Incident nur im Auditlog, nicht in der Fachansicht | P2 | umgesetzt: append-only Verlauf je Incident mit Rolle statt Person |
| M1 | Vertrieb | Ohne Azure ist der KI-Pfad gesperrt; es fehlt ein Demo-Mandant mit synthetischen Daten | P2 | umgesetzt: `AI_BACKEND=demo` mit Seed, extraktiven Antworten und Beispiel-Messreihe |
| U5 | Bedienung | Kein formaler Barrierefreiheitsnachweis (WCAG 2.2 AA / BITV 2.0) | P2 | technischer Teil umgesetzt (Kontrast-, Struktur- und Sprachprüfung); manueller Prüfbericht bleibt externes Gate |
| U6 | Bedienung | Nur Deutsch; internationale Werke benötigen DE/EN | P3 | umgesetzt: DE/EN mit Browser-Erkennung, zweisprachigen Hinweisen und Vollständigkeitstest |
| D6 | Werk | Keine Reaktions- und Behebungszeiten, keine Sicht auf Wiederholungsfehler je Anlage; Werksleitung kann den Nutzen des Workflows nicht belegen | P2 | umgesetzt: Kennzahlen je Anlage (MTTA, MTTR, Wiedereröffnung, Störungsabstand, Wiederholungsfehler) ohne Personenbezug, CSV-Export |
| D8 | Werk/Sicherheit | Die Audit-Hashkette wurde geschrieben, aber nie geprüft; ein Manipulationsschutz ohne Verifikation trägt im ISO-27001-/TISAX-Audit nicht | P1 | umgesetzt: nächtliche Verifikation je Mandant im Lifecycle-Job mit Ankern in Log Analytics, Prüfung auf Abruf für Admins, Runbook für Kettenbrüche |
| D9 | Werk/Recht | Kein technischer Legal Hold: Bei Rechtsstreit, Behördenanfrage oder Gewährleistungsfall hätte der nächtliche Löschlauf Beweise vernichtet | P1 | umgesetzt: Hold je Datenklasse in der Datenbank-Löschfunktion, Pflicht-Wiedervorlage ohne automatische Aufhebung, nur für Admins, auditiert |
| D10 | Werk/Datenschutz | Datenschutzanträge konnten gestellt, aber in der Anwendung nicht bearbeitet werden; Fristwahrung und Begründung waren nicht nachweisbar | P2 | umgesetzt: Bearbeitungsworkflow für Admins mit begründeter Entscheidung, Vorgangsnummer, Vier-Augen-Regel, Fristmahnung und Legal-Hold-Hinweis |
| D11 | Werk/Qualität | Jedes hochgeladene PDF wurde sofort zur KI-Quelle: keine Freigabe, kein Revisionsstand, kein Rückzug. Eine veraltete oder manipulierte Anleitung wäre unbemerkt zitiert worden; gelenkte Dokumente (ISO 9001 Abschnitt 7.5.3, IATF 16949 Abschnitt 7.5.3.2) waren nicht abbildbar | P1 | umgesetzt: Dokumentenlenkung mit Entwurf, Freigabe durch eine zweite Person, Revision und Dokumentnummer, Rückzug mit Grund, Überprüfungstermin und Verlauf je Dokument; die KI zitiert nur freigegebene Revisionen |
| S4 | ERP | Kein Live-Connector (S/4HANA OData, SAP BTP Integration Suite) | P3 | Roadmap, benötigt Bedrohungsmodell und Datenvertrag je Kunde |
| S5 | ERP | Keine automatische Benutzer-/Gruppenprovisionierung (SCIM aus Entra ID) | P3 | Roadmap |
| D5 | Werk/Sicherheit | TISAX-/ISO-27001-Evidenzpaket fehlt | P2 | externes Gate |
| D7 | Werk/Mitbestimmung | Für die Betriebsvereinbarung fehlte eine belastbare Aufstellung, welche Daten über Beschäftigte gespeichert und ausgewertet werden; die Selbstauskunft deckte Dokumente, Reviews und Workflow-Schritte nicht ab | P1 | umgesetzt: Inventar als Code mit CI-Gate gegen das Schema, erzeugte technische Anlage, Übersicht für Beschäftigte, Selbstauskunft v2 |

## Umgesetzt in diesem Inkrement

- **Asset Register:** Felder Technischer Platz und Equipment mit SAP-Längenprüfung, deutsche Labels, Hinweis auf fehlende SAP-Referenzen, Stammdatenimport mit Vorlage. Ein ungültiger Datensatz verwirft den gesamten Import, damit keine halb importierten Stammdaten entstehen.
- **SAP-PM-Übergabe:** Gefilterte Incidents werden als Semikolon-CSV mit UTF-8-BOM erzeugt (Excel-kompatibel). Priorität: kritisch/P1 → 1, P2 → 2, Warnung/P3 → 3, OK/P4 → 4. Die Meldungsart ist wählbar (Standard `M2`). Export und Auditereignis zählen fehlende Technische Objekte.
- **Leitstand:** Handlungsbedarf aus dem Incident-Workflow und eine Einrichtungsliste (Assets, SAP-Referenzen, Dokumente, KI- und Datenschutzhinweis) mit direktem Sprung zum nächsten offenen Schritt.
- **Schema:** `assets.functional_location` und `assets.equipment_number` als idempotente Migration; der Runtime-Start prüft die Spalten und bricht bei fehlender Migration klar ab.

## Umgesetzt im Folgeinkrement: 8D-light und Verlauf

- **Pflichtfelder nach Schwere:** Incidents mit Schwere kritisch, P1 oder P2 sind 8D-pflichtig. Vor „Als behoben melden“ müssen D3 Sofortmaßnahme, D4 Ursache und D5/D6 Abstellmaßnahme dokumentiert sein, vor der Abnahme D7 Wirksamkeitsprüfung. Für übrige Incidents ist mindestens die Abstellmaßnahme Pflicht. Je Feld sind mindestens 10 Zeichen gefordert, damit Platzhalter wie „ok“ nicht zählen.
- **Durchsetzung im Repository:** Die Regeln gelten serverseitig im Statuswechsel, nicht nur in der Oberfläche. Analyseänderungen prüfen die Version (`updated_at`), damit parallele Bearbeitungen sich nicht still überschreiben; abgeschlossene Incidents sind unveränderlich.
- **Verlauf:** Tabelle `incident_events` mit Anlage, Statuswechseln und Analyseänderungen. Die Runtime-Rolle darf nur einfügen und lesen; Löschung erfolgt ausschließlich über die Lifecycle-Funktion zusammen mit dem Incident. Angezeigt wird die Rolle, nicht die Person; die pseudonymisierte Kennung bleibt Auditnachweis.
- **Mitbestimmung:** Die Oberfläche weist darauf hin, Ursachen technisch zu beschreiben und keine Personennamen oder Schuldzuweisungen einzutragen. Ob Freitextfelder einer Betriebsvereinbarung bedürfen, bleibt eine instanzbezogene Bewertung.
- **SAP-Übergabe:** Der Langtext der Meldung enthält die dokumentierten 8D-Inhalte.

## Umgesetzt: Demo-Mandant

- **Ein Klick zur vollständigen Geschichte:** Im leeren Mandanten lädt ein Supervisor vier fiktive Anlagen (eine bewusst ohne SAP-Referenz), zwei freigegebene synthetische Handbücher, eine neue Revision als Entwurf und fünf Incidents, die jeden Workflow-Zustand zeigen, inklusive gesperrter Abnahme mangels D7. Der Verlauf ist über vier Wochen gestaffelt (Wiederholungsfehler an Presse 05, eine Wiedereröffnung), damit die Kennzahlen aussagekräftig sind. Rückdatieren kann nur das Entwicklungs-Repository; in PostgreSQL gelten immer Serverzeiten.
- **Keine Scheinintelligenz:** Der Demo-Pfad erzeugt keinen Text, sondern zitiert Sätze unverändert mit Seitenbeleg. Die Auswahl deckt Teilfragen einzeln ab und verwirft schwache Stichworttreffer. Die Antwort sagt ausdrücklich „Demo-Antwort ohne Sprachmodell“, die Provenienz nennt keinen Modellanbieter.
- **Gleiche Governance:** Verwendungszweck-Sperren, Zitatprüfung, KI-Nutzerhinweis, Review, Vier-Augen-Prinzip und Export laufen unverändert.
- **Nicht verwechselbar:** Banner auf jeder Seite, Präfix `DEMO` in Titeln, Dokumenten und SAP-Kurztexten, Releasezustand `demo`, Region „lokal“. Die Konfiguration verweigert `demo` in Produktion und hinter Entra ID; Demodaten werden nie in einen Mandanten mit Daten gemischt.

## Umgesetzt: Instandhaltungskennzahlen

- **Je Anlage, nie je Person:** Reaktionszeit (Anlage bis erster Bearbeitungsschritt), Behebungszeit (bis zur letzten Meldung „Behoben“), Wiedereröffnungen, mittlerer Störungsabstand und Wiederholungsfehler (zwei Incidents innerhalb von 30 Tagen). Die Abfrage liefert keine Akteursdaten; eine Leistungs- oder Verhaltenskontrolle nach § 87 Abs. 1 Nr. 6 BetrVG ist damit technisch nicht abbildbar.
- **Ehrliche Grundlage:** Gemessen werden Dokumentationszeitpunkte, keine Maschinen- oder SAP-Daten. Der Störungsabstand läuft in Kalenderzeit und wird ausdrücklich nicht als MTBF bezeichnet. Incidents ohne Verlauf (vor dessen Einführung) zählen mit, aber ohne Zeiten.
- **Leitstand:** Wiederholungsfehler der letzten 90 Tage erscheinen als Handlungsbedarf mit Sprung zu den Kennzahlen.
- **Export:** CSV je Anlage für Supervisor und Admin (`analysis:export`), Schutz vor Formel-Injection, Auditereignis `incident.kpi_export.generated` nur mit Zählwerten.
- **Skalierung:** eigene Abfrage über das Zeitfenster (bis 10.000 Incidents, danach Hinweis) statt der auf 250 Einträge begrenzten Incident-Liste; neuer Index `incidents(tenant_id, created_at DESC)`.

## Umgesetzt: Dokumentenlenkung

- **Entwurf vor Quelle:** Ein Upload ist ein Entwurf. Er wird geprüft, gespeichert und indexiert, aber weder gesucht noch zitiert, bis eine zweite Person ihn freigibt. Freigeben dürfen Supervisor und Admin (`document:release`); der eigene Upload ist für jede Rolle gesperrt, auch für Admins. Das begrenzt zugleich das Risiko einer vergifteten Wissensbasis: Ein einzelnes kompromittiertes Konto bringt keinen Text mehr in eine Antwort.
- **Revisionen:** Jedes Dokument trägt Revision und optionale Dokumentnummer. Eine neue Revision verweist auf ihre Vorgängerin; die Vorgängerin bleibt gültig, bis die neue freigegeben ist, und wird in derselben Transaktion zurückgezogen. Es gibt damit keinen Zeitpunkt mit zwei gültigen oder keiner gültigen Revision.
- **Rückzug:** Mit festem Grund (veraltet, inhaltlich fehlerhaft, Sicherheitsmitteilung des Herstellers, Anlage oder Verfahren entfällt), sofort wirksam und endgültig. Die Rückmeldung nennt, wie viele gespeicherte Antworten das Dokument zitieren; diese Antworten zeigen danach den Hinweis, sie nicht mehr zu verwenden.
- **Überprüfung:** Die Freigabe verlangt einen Überprüfungstermin innerhalb eines Jahres. Fällige Termine erscheinen im Leitstand. Ein überfälliger Termin sperrt die Quelle bewusst nicht, weil ein stiller Ausfall der Wissensbasis im Schichtbetrieb das größere Risiko wäre; die Bestätigung oder der Rückzug bleibt eine dokumentierte Entscheidung.
- **Durchsetzung:** Die Regeln gelten im Repository, nicht nur in der Oberfläche. PostgreSQL entscheidet, was freigegeben ist: Der Suchindex wird auf die freigegebenen Dokumente gefiltert, und jeder Treffer wird vor dem Modellaufruf erneut gegen die Datenbank geprüft. Der Demo-Pfad verwendet dieselbe Regel.
- **Nachweis:** Tabelle `document_events` (Upload, Freigabe, Rückzug, Überprüfung) als Verlauf je Dokument mit Rolle statt Person; die Runtime-Rolle darf nur einfügen und lesen. Auditereignisse `knowledge.document.released`, `release_denied`, `withdrawn` und `review_confirmed`. Zitate tragen die Revision, damit ein Review erkennt, auf welchem Stand eine Antwort beruht.
- **Altbestand:** Dokumente aus der Zeit vor der Einführung bleiben nutzbar, sind aber als „ohne dokumentierte Freigabe“ gekennzeichnet und im Leitstand als offene Aufgabe gezählt, bis eine zweite Person sie formal freigibt.

## Bewusste Grenzen

- Die SAP-Übergabe ist eine Datei, keine Schnittstelle. Feldnamen orientieren sich an den klassischen SAP-PM-Feldern der Meldung; Upload-Weg (z. B. LSMW, BTP-Flow), Meldungsart, Prioritätsschema und Pflichtfelder legt das SAP-Team des Kunden fest.
- Es wird keine SAP-Zertifizierung, Kompatibilitätsgarantie oder Integration behauptet.
- Der Stammdatenimport übernimmt keine personenbezogenen Spalten; nicht freigegebene Spalten verwerfen die Datei.
- Die Dokumentenlenkung ersetzt kein Dokumentenmanagementsystem. Sie kennt keine Verteiler, keine Kenntnisnahme-Bestätigung, keinen mehrstufigen Freigabeworkflow und keinen Abgleich mit dem Hersteller, ob eine neuere Revision existiert. Die Freigabe bestätigt, dass eine berechtigte zweite Person das Dokument geprüft hat; die fachliche Richtigkeit bleibt deren Verantwortung.
- Der Verlauf eines Dokuments wird mit dem Dokument gelöscht. Dauerhafter Nachweis ist das Auditprotokoll mit seiner eigenen Frist. Bereits akzeptierte Antworten werden beim Rückzug einer Quelle nicht automatisch widerrufen, sondern gekennzeichnet.
- Vier Augen sind eine Regel der Anwendung, keine Spaltenberechtigung der Datenbank: Die Runtime-Rolle darf `documents` ändern. Ein Angreifer mit Datenbankzugang der Anwendung wird durch das Auditprotokoll und dessen Kettenprüfung erkannt, nicht verhindert.

## Empfohlene nächste Schritte

1. ~~8D-light im Incident~~ (D1, D2): umgesetzt.
2. ~~Demo-Mandant~~ (M1): umgesetzt.
3. **Barrierefreiheit** (U5): automatisierte Prüfungen umgesetzt (siehe Kontrollmatrix); offen sind der manuelle Tastatur- und Screenreader-Test und ein Prüfbericht.
4. ~~DE/EN~~ (U6): umgesetzt, KI-Antworten folgen der Oberflächensprache (Prompt `2026-11-06.1`, Evaluation je Sprache). Die Sprachwahl gilt bewusst nur je Sitzung und wird nicht personenbezogen gespeichert.
5. ~~Instandhaltungskennzahlen~~ (D6): umgesetzt, einschließlich gestaffeltem Demo-Verlauf.
6. **Live-Connector-Pilot** (S4) erst nach Datenvertrag und Bedrohungsmodell mit einem konkreten Kunden.
7. ~~Dokumentenlenkung~~ (D11): umgesetzt. Offen für einen Folgeschritt: Kenntnisnahme neuer Revisionen durch die betroffenen Teams und eine Erinnerung vor Ablauf des Überprüfungstermins per E-Mail oder Teams.
