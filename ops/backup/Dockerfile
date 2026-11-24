FROM postgres:17.11-bookworm@sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994

RUN apt-get update && \
    apt-get install --yes --no-install-recommends ca-certificates restic && \
    rm -rf /var/lib/apt/lists/* && \
    install -d -o postgres -g postgres /var/backups/postgres

COPY ops/scripts/backup-postgres.sh /usr/local/bin/backup-postgres
COPY ops/scripts/backup-loop.sh /usr/local/bin/backup-loop

RUN chmod 0555 /usr/local/bin/backup-postgres /usr/local/bin/backup-loop

USER postgres
ENTRYPOINT ["/usr/local/bin/backup-loop"]
