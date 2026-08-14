FROM postgres:18.0-bookworm@sha256:3f55f8895c4ed50603e2fbdfc72fffeeaba3173321fee5cb825bbbeb30d9d854

RUN apt-get update && \
    apt-get install --yes --no-install-recommends ca-certificates restic && \
    rm -rf /var/lib/apt/lists/* && \
    install -d -o postgres -g postgres /var/backups/postgres

COPY ops/scripts/backup-postgres.sh /usr/local/bin/backup-postgres
COPY ops/scripts/backup-loop.sh /usr/local/bin/backup-loop

RUN chmod 0555 /usr/local/bin/backup-postgres /usr/local/bin/backup-loop

USER postgres
ENTRYPOINT ["/usr/local/bin/backup-loop"]
