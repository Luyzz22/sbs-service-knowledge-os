FROM postgres:17.10-bookworm@sha256:9b18b78397054fce88a9552e9d5a3ad5bb7fd258c5b3cc1c5028e46373d6ea8f

RUN apt-get update && \
    apt-get install --yes --no-install-recommends ca-certificates restic && \
    rm -rf /var/lib/apt/lists/* && \
    install -d -o postgres -g postgres /var/backups/postgres

COPY ops/scripts/backup-postgres.sh /usr/local/bin/backup-postgres
COPY ops/scripts/backup-loop.sh /usr/local/bin/backup-loop

RUN chmod 0555 /usr/local/bin/backup-postgres /usr/local/bin/backup-loop

USER postgres
ENTRYPOINT ["/usr/local/bin/backup-loop"]
