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
| D1 | Werk | Incidents ohne Ursache, Sofort- und Abstellmaßnahme (8D/A3) | P2 | Roadmap |
| D2 | Werk | Statusverlauf je Incident nur im Auditlog, nicht in der Fachansicht | P2 | Roadmap |
| M1 | Vertrieb | Ohne Azure ist der KI-Pfad gesperrt; es fehlt ein Demo-Mandant mit synthetischen Daten | P2 | Roadmap |
| U5 | Bedienung | Kein formaler Barrierefreiheitsnachweis (WCAG 2.2 AA / BITV 2.0) | P2 | externes Gate |
| U6 | Bedienung | Nur Deutsch; internationale Werke benötigen DE/EN | P3 | Roadmap |
| S4 | ERP | Kein Live-Connector (S/4HANA OData, SAP BTP Integration Suite) | P3 | Roadmap, benötigt Bedrohungsmodell und Datenvertrag je Kunde |
| S5 | ERP | Keine automatische Benutzer-/Gruppenprovisionierung (SCIM aus Entra ID) | P3 | Roadmap |
| D5 | Werk/Sicherheit | TISAX-/ISO-27001-Evidenzpaket fehlt | P2 | externes Gate |

## Umgesetzt in diesem Inkrement

- **Asset Register:** Felder Technischer Platz und Equipment mit SAP-Längenprüfung, deutsche Labels, Hinweis auf fehlende SAP-Referenzen, Stammdatenimport mit Vorlage. Ein ungültiger Datensatz verwirft den gesamten Import, damit keine halb importierten Stammdaten entstehen.
- **SAP-PM-Übergabe:** Gefilterte Incidents werden als Semikolon-CSV mit UTF-8-BOM erzeugt (Excel-kompatibel). Priorität: kritisch/P1 → 1, P2 → 2, Warnung/P3 → 3, OK/P4 → 4. Die Meldungsart ist wählbar (Standard `M2`). Export und Auditereignis zählen fehlende Technische Objekte.
- **Leitstand:** Handlungsbedarf aus dem Incident-Workflow und eine Einrichtungsliste (Assets, SAP-Referenzen, Dokumente, KI- und Datenschutzhinweis) mit direktem Sprung zum nächsten offenen Schritt.
- **Schema:** `assets.functional_location` und `assets.equipment_number` als idempotente Migration; der Runtime-Start prüft die Spalten und bricht bei fehlender Migration klar ab.

## Bewusste Grenzen

- Die SAP-Übergabe ist eine Datei, keine Schnittstelle. Feldnamen orientieren sich an den klassischen SAP-PM-Feldern der Meldung; Upload-Weg (z. B. LSMW, BTP-Flow), Meldungsart, Prioritätsschema und Pflichtfelder legt das SAP-Team des Kunden fest.
- Es wird keine SAP-Zertifizierung, Kompatibilitätsgarantie oder Integration behauptet.
- Der Stammdatenimport übernimmt keine personenbezogenen Spalten; nicht freigegebene Spalten verwerfen die Datei.

## Empfohlene nächste Schritte

1. **8D-Light im Incident** (D1, D2): Ursache, Sofortmaßnahme, Abstellmaßnahme, Wirksamkeitsprüfung als Pflichtfelder vor der Abnahme, dazu ein sichtbarer Statusverlauf je Incident. Benötigt eine Tabelle `incident_events` mit Insert-only-Rechten.
2. **Demo-Mandant** (M1): synthetische Assets, Messreihen, Dokumentauszüge und Incidents für Vertriebsdemos ohne Kundendaten und ohne Azure-Kosten, klar als Demo gekennzeichnet.
3. **Barrierefreiheitsprüfung** (U5): Tastatur- und Screenreader-Test der Kernabläufe, Kontrastmessung, Ergebnis als Evidenz in der Kontrollmatrix.
4. **DE/EN** (U6): Textkatalog statt Inline-Strings, Sprachwahl je Benutzer.
5. **Live-Connector-Pilot** (S4) erst nach Datenvertrag und Bedrohungsmodell mit einem konkreten Kunden.
