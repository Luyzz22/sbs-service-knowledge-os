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

1. Der angemeldete Nutzer kann einen unmittelbaren Export der ihm zugeordneten Interaktionen, Notices, Incidents und Anträge erzeugen.
2. Auskunft, Berichtigung, Einschränkung, Löschung und Widerspruch werden als pseudonymisierter Antrag mit interner 28-Tage-Zielfrist eingereiht.
3. DSR-Owner prüft Identität, Vertretungsmacht, Scope, Rechte Dritter, Aufbewahrungspflichten und Legal Holds.
4. Für Löschung werden betroffene Analysen, Incidents, Notices, Dokumente und externe Empfänger bestimmt. Dokumentlöschung nutzt dieselbe Search-/Blob-/DB-Propagation.
5. Backups und Soft-Delete-Horizonte werden in der Antwort transparent genannt; gesperrte Wiederherstellung und späteste physische Vernichtung werden dokumentiert.
6. Abschluss oder begründete Ablehnung wird mit Evidence Reference und Zeitpunkt gespeichert. Der aktuelle UI-Umfang stellt den Antrag; die Bearbeitungsoberfläche/Case-Management-Integration bleibt ein organisatorisches Gate.

## Legal Hold

Ein Legal Hold ist kein Umgebungswert, der Fristen global abschaltet. Er braucht Fall-ID, Rechtsgrund, Scope, approvierende Rolle, Beginn, Reviewdatum und Ende. Bis eine technisch scoped Hold-Funktion implementiert ist, muss ein Hold über kontrollierte Datenbank-/Backup-Verfahren durch den DSR- und Legal-Owner umgesetzt und separat evidenziert werden.

## Verifikation

Monatlich: letzte Jobausführung, Fehlerzahl, abgelaufene Datensätze, Search-Leerprüfung und Blobstatus prüfen. Quartalsweise: Testdokument mit kurzer Frist durch alle Systeme löschen und Backup-/Soft-Delete-Horizont belegen. Jede Policyänderung erzeugt neue ID, Regressionstest und aktualisierte Informationspflicht.
