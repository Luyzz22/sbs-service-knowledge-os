FROM postgres:18.6-bookworm@sha256:7d2695c3aa88e792e8b3b233e7e4adb296a20412c6c0ca361e3edaaacfada108

RUN apt-get update && \
    apt-get install --yes --no-install-recommends ca-certificates restic && \
    rm -rf /var/lib/apt/lists/* && \
    install -d -o postgres -g postgres /var/backups/postgres

COPY ops/scripts/backup-postgres.sh /usr/local/bin/backup-postgres
COPY ops/scripts/backup-loop.sh /usr/local/bin/backup-loop

RUN chmod 0555 /usr/local/bin/backup-postgres /usr/local/bin/backup-loop

USER postgres
ENTRYPOINT ["/usr/local/bin/backup-loop"]
