# Nachweise für Audits

Dieses Runbook beschreibt, wie ein Betreiber einem internen oder externen Audit (ISO/IEC 27001, TISAX-Assessment, Kundenaudit, Datenschutzprüfung) Evidenz aus einer HydraulikDoc-Instanz bereitstellt. Die Kontrolltests belegen die technische Durchsetzung in dieser Instanz für einen Zeitraum. Sie sind keine Konformitätsaussage und ersetzen weder das Audit noch eine Zertifizierung.

## Rollen

| Rolle | Entra-App-Rolle | Zugriff |
| --- | --- | --- |
| Prüfer | `HydraulikDoc.Auditor` | Seiten „Nachweise“, „Governance“ (eigene Hinweise und Datenschutzanträge) und „System“. Kein Zugriff auf Assets, Dokumente, KI-Antworten oder Incidents, keine schreibende Funktion außer der Auditkettenprüfung. |
| Admin | `HydraulikDoc.Admin` | Zusätzlich zur operativen Arbeit die Seite „Nachweise“, um ein Audit vorzubereiten. |

Die Prüferrolle ist für Personen ohne operative Rolle gedacht (Revision, ISMS-Beauftragte, externe Auditoren mit Gastkonto). Wer zusätzlich Techniker, Supervisor oder Admin ist, erhält die operative Rolle; die Unabhängigkeit der prüfenden Person stellt die Rollenvergabe in Entra sicher, nicht die Anwendung. Supervisor und Techniker sehen die Seite nicht.

## Ablauf

1. **Zugang:** Der prüfenden Person in Entra die App-Rolle `HydraulikDoc.Auditor` zuweisen, befristet für die Dauer des Audits.
2. **Kontrolltests ausführen:** Auf der Seite „Nachweise“ den Zeitraum wählen (30, 90 oder 365 Tage) und die Kontrolltests starten. Jeder Lauf erzeugt das Auditereignis `evidence.controls.evaluated` mit der Zahl der Abweichungen.
3. **Ergebnis lesen:** Die Tabelle zeigt je Kontrolle Ergebnis, geprüfte Fälle, Befunde und abgewiesene Versuche. Die Detailansicht nennt Ziel, Prüfmethode, Normbezug und die betroffenen Datensätze.
4. **Auditprotokoll sichten:** Die Ansicht filtert nach Ergebnis und Bereich und zeigt keine Personen.
5. **Nachweispaket erstellen** und herunterladen. Die angezeigte SHA-256-Summe der Datei getrennt vom Paket übermitteln. Der Lauf erzeugt `evidence.bundle.generated` mit der Paketkennung.
6. **Zugang entziehen**, sobald das Audit abgeschlossen ist.

## Kontrollen

Eine **technisch erzwungene** Kontrolle ist eine Regel, die die Anwendung niemanden brechen lässt. Der Test liest die gespeicherten Daten erneut und wendet die Regel unabhängig von dem Code an, der sie durchgesetzt hat; ein Befund bedeutet, dass die Regel umgangen wurde, etwa durch eine direkte Änderung in der Datenbank. Eine **überwachte** Kontrolle ist eine Frist oder ein Zustand, den Menschen einhalten müssen; ein Befund ist ein offener Punkt. Gibt es im Zeitraum keinen Fall, lautet das Ergebnis „Kein Fall im Zeitraum“ und nie „Wirksam“.

| ID | Kontrolle | Art | Bezug |
| --- | --- | --- | --- |
| DOC-01 | Dokumente gibt eine zweite Person frei | erzwungen | ISO/IEC 27001:2022 A.5.3; ISO 9001:2015 7.5.2, 7.5.3 |
| DOC-02 | Die KI zitiert nur freigegebene Dokumente | erzwungen | ISO 9001:2015 7.5.3; Verordnung (EU) 2024/1689 Art. 10 |
| DOC-03 | Freigegebene Dokumente sind formal freigegeben und überprüft | überwacht | ISO 9001:2015 7.5.3 |
| AI-01 | Sicherheitsrelevante KI-Antworten akzeptiert eine zweite Person | erzwungen | ISO/IEC 27001:2022 A.5.3; Verordnung (EU) 2024/1689 Art. 14 |
| AI-02 | Prüfentscheidungen sind endgültig, begründet und von der zuständigen Rolle | erzwungen | Verordnung (EU) 2024/1689 Art. 14; ISO/IEC 27001:2022 A.5.36 |
| AI-03 | Antworten warten nicht länger als 72 Stunden auf die zweite Person | überwacht | Verordnung (EU) 2024/1689 Art. 14 |
| AI-04 | Der KI-Nutzerhinweis ist vor der ersten Nutzung bestätigt | erzwungen | Verordnung (EU) 2024/1689 Art. 4, Art. 50 |
| LIM-01 | Betriebsgrenzen gibt eine zweite Person frei | erzwungen | ISO/IEC 27001:2022 A.5.3; ISO 9001:2015 7.5.3 |
| LIM-02 | Gültige Betriebsgrenzen stützen sich auf eine freigegebene Quelle | überwacht | ISO 9001:2015 7.5.3 |
| INC-01 | Incidents schließt eine berechtigte Rolle mit vollständiger Analyse | erzwungen | ISO 9001:2015 10.2; IATF 16949:2016 10.2.3 |
| PRIV-01 | Datenschutzanträge werden fristgerecht entschieden | überwacht | DSGVO Art. 12 Abs. 3; ISO/IEC 27001:2022 A.5.34 |
| RET-01 | Löschfristen werden durchgesetzt | überwacht | DSGVO Art. 5 Abs. 1 lit. e; ISO/IEC 27001:2022 A.8.10 |
| RET-02 | Legal Holds werden fristgerecht wiedervorgelegt | überwacht | ISO/IEC 27001:2022 A.5.28, A.5.33 |
| LOG-01 | Das Auditprotokoll ist unverändert | erzwungen | ISO/IEC 27001:2022 A.8.15; Verordnung (EU) 2024/1689 Art. 12 |

Die Normbezüge ordnen einen Test der Anforderung zu, die er stützt. Ob die Anforderung für die Organisation gilt und vollständig erfüllt ist, bewertet das Audit. Für TISAX gibt es bewusst keine Zuordnung zu einzelnen Fragen des VDA-ISA-Katalogs; sie gehört in die Selbstauskunft des Betreibers.

## Umgang mit Befunden

- **Abweichung einer erzwungenen Kontrolle:** als Sicherheitsvorfall nach [Incident Response](incident-response.md) behandeln. Die betroffenen Datensätze nicht korrigieren, bevor Datenbank-Snapshot, Nachweispaket und Auditkettenprüfung gesichert sind. Zugriffe der Datenbank-Administrations- und Owner-Rollen im Zeitraum prüfen.
- **Offene Punkte einer überwachten Kontrolle:** im jeweiligen Arbeitsbereich erledigen (Dokument überprüfen, Antwort entscheiden, Antrag bearbeiten, Legal Hold wiedervorlegen) und den Test erneut ausführen. Überfällige Löschfristen deuten auf einen ausgefallenen Lifecycle-Job; dessen Ausführung und Log prüfen.
- **Nicht prüfbare Fälle:** Antworten, deren Dokument inzwischen gelöscht wurde, und Einträge aus der Zeit vor Einführung einer Regel werden gezählt, aber nicht bewertet.
- **Unvollständiges Ergebnis:** Über 10.000 Zeilen je Datenart bricht die Abfrage ab und markiert die betroffenen Kontrollen. Einen kürzeren Zeitraum wählen.
- **DOC-02** rechnet mit fünf Minuten Toleranz, weil eine laufende Abfrage ein Dokument noch zitieren darf, das währenddessen zurückgezogen wird.

## Nachweispaket

Die ZIP-Datei enthält:

| Datei | Inhalt |
| --- | --- |
| `controls.json`, `controls.csv` | Ergebnis jeder Kontrolle mit Methode, Normbezug und Befunden |
| `audit-events.jsonl` | Auditereignisse des Zeitraums, je Zeile ein Ereignis, höchstens 50.000 |
| `configuration.json` | Konfiguration der Instanz ohne Geheimnisse (Version, Region, Fristen, Evidence-IDs) |
| `manifest.json` | Zeitraum, Zusammenfassung, Kopf der Auditkette, SHA-256 jeder Datei und Siegel |
| `README.txt` | Kurzbeschreibung in der Sprache der Oberfläche |

Prüfung der Integrität:

```bash
python ops/scripts/verify-evidence-bundle.py hydraulikdoc-nachweispaket-<datum>-<kennung>.zip
```

Ohne Geheimnis prüft das Skript jede Datei gegen die SHA-256-Summe im Manifest; das kann auch die empfangende Stelle. Mit gesetztem `AUDIT_HMAC_KEY` prüft der Betreiber zusätzlich das Siegel und bestätigt damit, dass diese Instanz das Paket erzeugt hat. Das Siegel ist ein HMAC und keine digitale Signatur: Es beweist Dritten nichts. Den Bezug nach außen stellt der Kopf der Auditkette im Manifest her, der mit den nächtlich außerhalb der Datenbank gespeicherten Ankern verglichen werden kann.

## Personenbezug

- Kontrolltests vergleichen Pseudonyme zweier Schritte nur auf Gleichheit. Ein Befund nennt den Datensatz, nie eine Person.
- Das Auditprotokoll auf der Seite zeigt weder Namen noch Pseudonyme.
- Im Nachweispaket sind Akteure und Objekte durch einen Alias ersetzt, der nur in diesem Paket gilt. Zwei Pakete lassen sich darüber nicht verknüpfen. Nur der Betreiber kann einen Alias mit dem Instanzgeheimnis zurückführen, und das nur anlassbezogen nach dem Verfahren der Betriebsvereinbarung.
- Das Paket bleibt pseudonymisiertes Personendatum. Weitergabe an externe Auditoren nur auf Grundlage einer Vertraulichkeitsvereinbarung und über einen geschützten Kanal.

## Grenzen

- Geprüft wird, was die Datenbank zum Zeitpunkt des Laufs enthält. Ein Angreifer mit Schreibzugriff auf die Datenbank kann auch Belege verändern; dagegen stehen die Auditkette und ihre externen Anker, nicht der Kontrolltest.
- Die Tests laufen auf Abruf. Ein nächtlicher Lauf mit Alarm ist nicht umgesetzt, weil die Lifecycle-Rolle die dafür nötigen Tabellen bewusst nicht lesen darf.
- KI-Antworten werden nach der Aufbewahrungsfrist gelöscht (Standard 90 Tage). Für längere Zeiträume liefern die KI-Kontrollen nur die noch vorhandenen Antworten.
- Organisatorische Kontrollen (Schulung, Rollenvergabe, Lieferanten, physische Sicherheit, Penetrationstest) sind nicht Gegenstand der Tests.
