# Optionales Private-Edge-Profil

Das Compose-/Traefik-Profil ist ein lokaler bzw. kundeneigener Betriebsadapter, nicht der freigegebene Azure-Produktionspfad. Es startet standardmäßig mit `AI_BACKEND=disabled`, lokaler Argon2id-Anmeldung und PostgreSQL. Es enthält keinen Qdrant-, LlamaCloud-, Gemini- oder externen OpenAI-Datenpfad.

## Einsatzgrenze

Ohne separate Architektur- und Compliance-Freigabe darf dieses Profil nicht mit der Azure-Produktionsbehauptung, Entra-Sicherheitsgrenze oder regionalen Azure-AI-Konfiguration gleichgesetzt werden. Ein produktiver Private-Edge-Betrieb braucht insbesondere SSO, zentralen Secret Store, Malware-Gate, Monitoring/SIEM, Patchprozess, Restoretest, Retentionjob und externen Penetrationstest.

## Hostvorbereitung

1. Unterstütztes Debian/Ubuntu, verschlüsseltes Blockvolume, Docker Engine/Compose und restriktiver SSH-Zugang.
2. Nur TCP 80/443 öffentlich; SSH nur aus vertrauenswürdigen Netzen.
3. PostgreSQL- und Backupverzeichnisse mit minimalen Rechten anlegen.

```bash
sudo install -d -m 0750 -o 999 -g 999 /mnt/hydraulikdoc/postgres
sudo install -d -m 0750 -o 999 -g 999 /mnt/hydraulikdoc/backups
sudo install -d -m 0750 /opt/hydraulikdoc
```

`.env.example` nach `.env` kopieren, absolute Pfade setzen und alle Dateien aus `secrets/README.md` mit Modus `0600` anlegen. `LOCAL_USERS_JSON` enthält ausschließlich Argon2id-Hashes. Es existieren keine eingebauten Nutzer oder Passwörter.

## Deployment

```bash
cd /opt/hydraulikdoc
./ops/scripts/deploy.sh ghcr.io/luyzz22/sbs-service-knowledge-os <git-commit-sha>
```

Das Skript wärmt den inaktiven Slot, prüft den Health-Endpunkt und schaltet Traefik um. Nur immutable SHA-Tags verwenden.

## Backup

`BACKUP_ENABLED=true` erst nach Konfiguration eines freigegebenen, verschlüsselten Restic-Repositories aktivieren. Das private Profil erstellt PostgreSQL-Dumps und wendet die konfigurierten daily/weekly/monthly-Regeln an. Quartalsweise in eine isolierte Instanz wiederherstellen; `pg_restore --list` allein ersetzt keinen fachlichen und RLS-bezogenen Restoretest.
