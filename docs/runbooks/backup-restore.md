# Backup and Restore Runbook

## Produktionsbaseline Azure

PostgreSQL Flexible Server ist mit zonenredundanter Hochverfügbarkeit, 14 Tagen Backup-Retention und ohne Geo-Redundanz konfiguriert. Blob Storage nutzt ZRS, sieben Tage Soft Delete und Change Feed. Azure AI Search wird aus den privaten Originaldokumenten reproduziert und gilt nicht als führendes Backup. Key Vault besitzt Soft Delete und Purge Protection.

Ein Applikationslöschvorgang entfernt aktive Search-/Blob-Daten sofort aus dem Nutzungspfad; Azure Blob Soft Delete kann den Inhalt noch sieben Tage und PostgreSQL Point-in-Time Backup Daten bis zu 14 Tage wiederherstellbar halten. Diese Zerstörungshorizonte müssen in Datenschutzhinweisen und DSR-Antworten korrekt beschrieben werden.

## RPO/RTO

RPO und RTO werden nicht aus den Azure-Einstellungen behauptet. Vor Kundenfreigabe müssen sie vertraglich festgelegt und durch einen realen Restore- und Failovertest bestätigt werden.

## Quartalsweiser Restore-Drill

1. Change-/Incident-Ticket und isolierte Restore-Resource-Group in einer genehmigten deutschen Region anlegen.
2. PostgreSQL auf einen definierten Zeitpunkt in einen getrennten Server wiederherstellen.
3. Zugriff nur dem Restore-Team geben; keine Produktions-App verbinden.
4. Schema, RLS/FORCE RLS, Tabellenanzahl, Audit-Hashverkettung und repräsentative tenant-isolierte Abfragen prüfen.
5. Einen privaten Blob-Testsatz wiederherstellen bzw. aus zulässigem Originalbestand bereitstellen.
6. Azure AI Search in einen separaten Testindex neu aufbauen und Quellen-/Tenant-Negativtests ausführen.
7. Messwerte für tatsächliches RPO/RTO, Datenlücken und manuelle Schritte dokumentieren.
8. Restore-Ressourcen und Exporte nach Evidenzfreigabe sicher löschen.

## Disaster Recovery

Die aktuelle Architektur priorisiert deutsche Regionsbindung und zonale Resilienz; sie verspricht kein automatisches regionenübergreifendes Failover. Eine zweite Region darf erst nach Datenschutz-/Transfer-, Modellverfügbarkeits-, DNS-, Key- und Konsistenzdesign ergänzt werden.

## Private-Edge-Profil

Das optionale Compose-Profil erzeugt verschlüsselte Restic-Snapshots eines PostgreSQL-Dumps, sofern `BACKUP_ENABLED=true` und ein freigegebenes Repository konfiguriert ist. Der Container-Datenbanknutzer des privaten Profils ist für vollständige Dumps ausgelegt; Azure nutzt stattdessen Managed Backups. Ein Backup gilt erst nach erfolgreichem Restoretest als nutzbar.
