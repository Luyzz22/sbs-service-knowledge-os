# Hetzner production deployment

This deployment keeps Traefik and the application on a public proxy network while PostgreSQL and Qdrant remain on an internal Docker network. Application releases use blue/green containers and switch Traefik only after the new container is healthy.

## Host preparation

1. Provision a supported Debian or Ubuntu host and attach an encrypted Hetzner block volume.
2. Install Docker Engine with the Compose plugin and `curl` for deployment health checks.
3. Point `APP_HOST` at the server and allow inbound TCP ports 80 and 443 only. Limit SSH to trusted operator addresses.
4. Mount the Hetzner volume, then create application directories. PostgreSQL uses container UID/GID `999`; the application image uses `10001`.

```bash
sudo install -d -m 0750 -o 999 -g 999 /mnt/sbs-data/postgres
sudo install -d -m 0750 /mnt/sbs-data/qdrant
sudo install -d -m 0750 -o 999 -g 999 /mnt/sbs-data/backups
sudo install -d -m 0750 /opt/sbs-service-knowledge-os
sudo chown -R "$USER":"$USER" /opt/sbs-service-knowledge-os /mnt/sbs-data/qdrant
```

Copy `.env.example` to `.env`, use absolute paths for the three data directories, and set `APP_HOST`, `ACME_EMAIL`, and the restic S3 repository. Create every file listed in `secrets/README.md` and apply `chmod 0600 secrets/*`.

Use a dedicated S3 bucket in a German or EU region. The backup job creates encrypted restic snapshots, applies daily/weekly/monthly retention, prunes expired data, and verifies a sample of stored data after every successful backup. Enable it with `BACKUP_ENABLED=true` only after the repository and credentials are configured.

## First deployment

Authenticate the host to GHCR, then deploy an immutable image tag:

```bash
cd /opt/sbs-service-knowledge-os
./ops/scripts/deploy.sh ghcr.io/luyzz22/sbs-service-knowledge-os <git-commit-sha>
```

The script starts platform services, warms the inactive application slot, waits for the Streamlit health endpoint, atomically changes Traefik routing, checks the public TLS endpoint, drains the old slot, and removes week-old unused images.

## GitHub configuration

Add these repository secrets:

- `HETZNER_HOST`
- `HETZNER_PORT`
- `HETZNER_USER`
- `HETZNER_DEPLOY_PATH` (for example `/opt/sbs-service-knowledge-os`)
- `HETZNER_SSH_PRIVATE_KEY`
- `HETZNER_SSH_KNOWN_HOSTS` (the pinned server host-key line)
- `GHCR_USERNAME`
- `GHCR_READ_TOKEN`

The deployment account must be restricted to this host and must be able to run Docker without an interactive password. Do not disable SSH host-key checking.

## Recovery verification

Schedule a quarterly restore drill into a separate PostgreSQL instance. A backup is not considered recoverable until `pg_restore --list` succeeds and representative application queries pass against the restored database.
