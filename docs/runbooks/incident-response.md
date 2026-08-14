# Security, Privacy and AI Incident Response

## Ziel

Ein gemeinsamer Prozess behandelt Cybersecurity-, Datenschutz-, Verfügbarkeits- und KI-Qualitätsereignisse. Rechts- und Behördenmeldungen werden durch die benannten Verantwortlichen entschieden, nicht automatisch durch die Anwendung.

## Schweregrade

| Stufe | Beispiel | Sofortmaßnahme |
| --- | --- | --- |
| P1 | aktiver tenant-übergreifender Zugriff, Credential-Abfluss, manipulierte Wartungsfreigabe, Malware mit Ausführung | Incident Commander, Zugriff eindämmen, Release stoppen, Beweise sichern |
| P2 | bestätigte Offenlegung eines Tenant-Dokuments, systematischer gefährlicher KI-Fehler, Retention-/Backup-Ausfall | betroffene Funktion sperren, Scope bestimmen, DSB/AI/Security Owner einbinden |
| P3 | begrenzte Fehlkonfiguration ohne bestätigten Zugriff, wiederholte Review-Eskalation | Ticket, Workaround, Ursachenanalyse und Frist |
| P4 | Best-Practice-Abweichung ohne unmittelbare Auswirkung | planmäßige Korrektur |

## Ablauf

1. **Erkennen und klassifizieren:** Zeitpunkt, Image Digest, Deployment Evidence ID, Tenantpseudonym, Providerstatus und Symptom erfassen. Keine Rohdokumente in Incidenttickets kopieren.
2. **Eindämmen:** GitHub-Deployment sperren, Entra-Zuweisung/Token oder Managed Identity nur gezielt entziehen, kompromittierte Revision deaktivieren, betroffene Upload-/KI-Funktion über Konfiguration blockieren.
3. **Beweise sichern:** Azure Activity Log, Entra Sign-in/Audit, WAF, Container Apps, Defender, PostgreSQL und unveränderte Audit-Hashkette exportieren. Aufbewahrung als Legal Hold nur nach dokumentierter Freigabe.
4. **Scope bestimmen:** betroffene Tenants, Zeitfenster, Datenkategorien, Rollen, Search-/Blob-/DB-Objekte, Modell/Prompt/Snapshot und externe Empfänger prüfen.
5. **Meldeentscheidung:** DSB bewertet Art. 33/34 DSGVO. NIS2-verantwortliche Stelle bewertet Frühwarnung/Meldung/Abschlussbericht. CRA-, Produktsicherheits- und Kundenpflichten werden getrennt geprüft. Fristen beginnen nicht erst mit technischer Vollanalyse.
6. **Beseitigen:** Secrets rotieren, Rechte korrigieren, fixen Digest durch vollständige CI schicken, Datenlöschung/-wiederherstellung kontrolliert durchführen.
7. **Wiederanlauf:** Tenant-Negativtest, E2E-Fachtest, WAF/Identity, Retention und Monitoring verifizieren; Incident Commander und Fachowner geben frei.
8. **Nachbereitung:** Ursachenanalyse, CAPA, Threat Model/System Card/Evalset aktualisieren, Lessons Learned und Wirksamkeitsprüfung terminieren.

## KI-spezifischer Ablauf

- Betroffenen Deploymentnamen, Snapshot, Promptversion, Source-Chunks und Reviewstatus feststellen.
- Output sperren; niemals nachträglich als akzeptiert markieren.
- Prüfen, ob Retrieval, Extraktion, Prompt Injection, Modellverhalten oder Human Review ursächlich war.
- Goldset um den Fall ergänzen und Regression über alle zugelassenen Use Cases ausführen.
- Bei sicherheitsrelevantem Muster das Use-Case-Gate deaktivieren, bis Fach- und AI-Governance-Review abgeschlossen sind.

## Kommunikationsregel

Nur benannte Rollen kommunizieren mit Kunden, Behörden, Presse und Anbieter. Aussagen enthalten bestätigte Fakten, Scope, Schutzmaßnahmen und nächste Aktualisierung; keine unbelegten Entwarnungen oder Compliance-Claims.
