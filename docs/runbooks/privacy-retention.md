# Datenschutz-, DSR- und Retention-Runbook

## Policy-Freigabe

Jede Record Class erhält im Verzeichnis der Verarbeitungstätigkeiten Zweck, Rechtsgrundlage, Betroffene, Datenkategorien, Empfänger, Beginn der Frist, Dauer, Löschmethode, Ausnahme/Legal Hold und Owner. Erst danach werden `RETENTION_POLICY_APPROVED=true` und eine versionierte `RETENTION_POLICY_ID` gesetzt.

Technische Defaults sind keine Rechtsfreigabe:

| Record Class | Default | Technische Behandlung |
| --- | ---: | --- |
| AI interaction | 90 Tage | Antwort/Provenienz; Rohfrage nur als Hash |
| Audit event | 730 Tage | pseudonymisierte Hashkette |
| Notice acceptance | 3650 Tage | Version, Digest, Subjektpseudonym |
| Privacy request | 1095 Tage | Status und Fristen ohne Freitext |
| Incident | 730 Tage | technische Beschreibung und Erstellerpseudonym |
| Uploaded content | 365 Tage | Blob, Search und Dokumentmetadaten |

## Tägliche Löschdurchsetzung

Der Container Apps Job `*-retention-lifecycle` läuft um 02:00 UTC:

1. liest Tenant-IDs ohne Inhaltsdaten;
2. findet abgelaufene Dokumente per RLS-Kontext;
3. löscht alle Search-Chunks in begrenzten Batches;
4. löscht den privaten Blob;
5. markiert und entfernt Dokumentmetadaten;
6. ruft eine `SECURITY DEFINER`-Funktion auf, die ausschließlich abgelaufene Datensätze dieses Tenants löscht;
7. schreibt ein pseudonymisiertes Erfolg-/Fehlerereignis.

Der Web-Runtime-Account besitzt weder DDL noch allgemeines `DELETE` und darf die Lifecycle-Funktionen nicht ausführen. Der getrennte Lifecycle-Account darf Tenant-IDs über eine SECURITY-DEFINER-Funktion aufzählen, RLS-gebunden abgelaufene Dokumente markieren, Auditereignisse schreiben und die tenant-gebundene Purge-Funktion aufrufen; auch er besitzt kein DDL und kein allgemeines `DELETE`. Ein Fehler bei einem Tenant führt zu einem fehlgeschlagenen Job und darf nicht als Gesamterfolg gewertet werden.

## Betroffenenantrag

1. Der angemeldete Nutzer kann einen unmittelbaren Export (Schema `hydraulikdoc.subject-export.v2`) der ihm zugeordneten KI-Interaktionen, Hinweisbestätigungen, hochgeladenen Dokumente, abgegebenen Reviews, gemeldeten Incidents, eigenen Workflow-Schritte und Anträge erzeugen. Welche Felder enthalten sind und welche nur auf Antrag beauskunftet werden (Sicherheitsprotokoll), steht in der [technischen Anlage zur Betriebsvereinbarung](../compliance/works-council-annex.md).
2. Auskunft, Berichtigung, Einschränkung, Löschung und Widerspruch werden als pseudonymisierter Antrag mit interner 28-Tage-Zielfrist eingereiht.
3. DSR-Owner prüft Identität, Vertretungsmacht, Scope, Rechte Dritter, Aufbewahrungspflichten und Legal Holds.
4. Für Löschung werden betroffene Analysen, Incidents, Notices, Dokumente und externe Empfänger bestimmt. Dokumentlöschung nutzt dieselbe Search-/Blob-/DB-Propagation.
5. Backups und Soft-Delete-Horizonte werden in der Antwort transparent genannt; gesperrte Wiederherstellung und späteste physische Vernichtung werden dokumentiert.
6. Abschluss oder begründete Ablehnung wird mit Evidence Reference und Zeitpunkt gespeichert. Der aktuelle UI-Umfang stellt den Antrag; die Bearbeitungsoberfläche/Case-Management-Integration bleibt ein organisatorisches Gate.

## Legal Hold

Ein Legal Hold ist kein Umgebungswert, der Fristen global abschaltet, sondern ein Datensatz je Mandant in `legal_holds`. Admins setzen ihn in der Governance-Seite (Berechtigung `legal_hold:manage`):

1. **Anlegen:** Aktenzeichen ohne Personennamen, Grund (Rechtsstreit, Behördenanfrage, interne Untersuchung, Gewährleistung/Produkthaftung), betroffene Datenklassen (Record Classes) und eine Wiedervorlage innerhalb eines Jahres. Das Auditereignis `legal_hold.created` hält Grund und Scope fest.
2. **Wirkung:** `purge_expired_tenant_data` überspringt jede Datenklasse unter aktivem Hold, und `list_expired_documents` liefert keine Dokumente, solange `uploaded_content` gehalten wird. Der Hold gilt für Fristabläufe und ersetzt keine Sperre einzelner Löschanträge; ein Löschantrag nach Art. 17 während eines Holds wird mit Verweis auf Art. 17 Abs. 3 lit. e begründet abgelehnt oder zurückgestellt.
3. **Wiedervorlage:** Ein Hold endet nie automatisch. Ist die Wiedervorlage fällig, mahnen Leitstand und Governance-Seite. Die Rechtsabteilung bestätigt die Weitergeltung durch einen neuen Hold mit neuem Datum, danach wird der alte aufgehoben; oder sie hebt ihn auf.
4. **Aufheben:** nur nach bestätigter Abstimmung mit der Rechtsabteilung. Danach greifen die regulären Fristen beim nächsten nächtlichen Lauf. Der aufgehobene Hold bleibt so lange erhalten wie Auditereignisse (`AUDIT_EVENT_RETENTION_DAYS`).

Die Runtime-Rolle darf an einem Hold nur die Aufhebung schreiben; Aktenzeichen, Grund und Scope sind nach dem Anlegen unveränderlich, Löschen ist nicht möglich. Backups unterliegen eigenen Fristen; ein Hold, der auch Backups erfassen soll, wird zusätzlich im Backup-Verfahren umgesetzt und evidenziert.

## Verifikation

Monatlich: letzte Jobausführung, Fehlerzahl, abgelaufene Datensätze, Search-Leerprüfung und Blobstatus prüfen. Quartalsweise: Testdokument mit kurzer Frist durch alle Systeme löschen und Backup-/Soft-Delete-Horizont belegen. Jede Policyänderung erzeugt neue ID, Regressionstest und aktualisierte Informationspflicht.
