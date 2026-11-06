# Technische Anlage zur Betriebsvereinbarung: personenbezogene Daten

Diese Datei wird aus `hydraulikdoc/personal_data.py` erzeugt (`python ops/scripts/render-works-council-annex.py`) und in CI gegen den Code geprüft. Löschfristen sind die technischen Standardwerte; die instanzbezogene Konfiguration (`*_RETENTION_DAYS`) und die Freigabe im Verarbeitungsverzeichnis gehen vor.

Gespeichert wird keine Klartextkennung: Personen erscheinen nur als nicht umkehrbares Pseudonym aus der Entra-Kennung. Name und E-Mail werden nur für die laufende Sitzung verwendet.

## Gespeicherte Felder

| Tabelle.Spalte | Inhalt | Zweck | Sichtbarkeit | Auswertung | Löschfrist | Auskunft (Art. 15) |
| --- | --- | --- | --- | --- | --- | --- |
| `documents.created_by_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Nachweis, wer ein Dokument in die Wissensbasis eingebracht hat | In der Oberfläche nicht angezeigt | Keine Auswertung je Person | 365 Tage (uploaded_content) | Selbstauskunft `documents_uploaded` |
| `analysis_runs.actor_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Zuordnung eigener KI-Anfragen für Auskunft und Vier-Augen-Prinzip | Nur für die Person selbst; Prüfer sehen nur die Antwort | Keine Auswertung je Person; Selbstfreigabe sicherheitsrelevanter Antworten wird gesperrt | 90 Tage (ai_interaction) | Selbstauskunft `analysis_runs` |
| `analysis_runs.question_hash` | SHA-256 der Frage; der Fragetext wird nicht gespeichert | Nachweis, auf welche Frage sich eine Antwort bezieht, ohne den Wortlaut aufzubewahren | In der Oberfläche nicht angezeigt | Keine Auswertung von Fragen oder Fragehäufigkeit je Person | 90 Tage (ai_interaction) | Selbstauskunft `analysis_runs` |
| `analysis_reviews.reviewer_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Nachweis der menschlichen Prüfung (Human Oversight) und des Vier-Augen-Prinzips | In der Oberfläche nicht angezeigt | Keine Auswertung je Person | 90 Tage (ai_interaction) | Selbstauskunft `reviews_given` |
| `incidents.created_by_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Nachweis, wer eine technische Auffälligkeit gemeldet hat | In der Oberfläche nicht angezeigt | Keine Auswertung je Person | 730 Tage (incident) | Selbstauskunft `incidents_created` |
| `incident_events.actor_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Rückverfolgbarkeit der Workflow-Schritte (8D, Abnahme) | Nur als Markierung „Sie“ für die Person selbst | Keine Auswertung je Person; Kennzahlen nur je Anlage | 730 Tage (incident) | Selbstauskunft `incident_steps` |
| `incident_events.actor_role` | App-Rolle der handelnden Person (z. B. Technician) | Nachvollziehbarkeit, welche Rolle einen Schritt ausgeführt hat | Im Incident-Verlauf für alle Rollen des Mandanten | Keine Auswertung je Person oder Rolle; Kennzahlen nur je Anlage | 730 Tage (incident) | Selbstauskunft `incident_steps` |
| `notice_acceptances.actor_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Nachweis der Kenntnisnahme von KI- und Datenschutzhinweis | Nur für die Person selbst (Einrichtungsfortschritt) | Keine Auswertung je Person | 3650 Tage (contract_acceptance) | Selbstauskunft `notice_acceptances` |
| `privacy_requests.subject_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Bearbeitung eigener Datenschutzanfragen | Nur für die Person selbst | Keine Auswertung je Person | 1095 Tage (data_subject_request) | Selbstauskunft `privacy_requests` |
| `audit_events.actor_token` | Pseudonym der Person (HMAC, nicht umkehrbar) | Sicherheits- und Compliance-Nachweis (Anmeldung, Export, Freigaben) | In der Oberfläche nicht angezeigt | Nur anlassbezogen bei Sicherheitsvorfällen nach Verfahren der Betriebsvereinbarung | 730 Tage (audit_event) | Auf Antrag über das Datenschutzteam; Sicherheitsprotokoll, nicht Teil der Selbstauskunft |
| `audit_events.resource_token` | Pseudonym des betroffenen Objekts (Dokument, Incident, Antwort, Anfrage) | Zuordnung eines Auditereignisses zu einem Objekt ohne Klartextkennung | In der Oberfläche nicht angezeigt | Keine Auswertung je Person | 730 Tage (audit_event) | Bezieht sich auf Objekte, nicht auf Personen |

## Ausgeschlossene Auswertungen

- Leistungs-, Tempo- oder Fehlerquoten je Person
- Rankings oder Vergleiche zwischen Beschäftigten oder Schichten
- Anwesenheits-, Arbeitszeit- oder Standortauswertung
- Auswertung von Fragetexten; gespeichert wird nur ein Hash

Instandhaltungskennzahlen (Reaktions- und Behebungszeit, Wiederholungsfehler) werden ausschließlich je Anlage gebildet; die zugrunde liegende Abfrage liefert keine Personendaten.
