FROM postgres:17.12-bookworm@sha256:1eff563f6c868b9b433566e9f3cf6e5c79fbd3b95bf70ec7277d376cdbfc50d7

RUN apt-get update && \
    apt-get install --yes --no-install-recommends ca-certificates restic && \
    rm -rf /var/lib/apt/lists/* && \
    install -d -o postgres -g postgres /var/backups/postgres

COPY ops/scripts/backup-postgres.sh /usr/local/bin/backup-postgres
COPY ops/scripts/backup-loop.sh /usr/local/bin/backup-loop

RUN chmod 0555 /usr/local/bin/backup-postgres /usr/local/bin/backup-loop

USER postgres
ENTRYPOINT ["/usr/local/bin/backup-loop"]
