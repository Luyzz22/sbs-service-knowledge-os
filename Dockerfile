# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN apt-get update && \
    apt-get install --yes --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN python -m venv "${VIRTUAL_ENV}"

WORKDIR /build
COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --require-hashes --requirement requirements.lock

FROM python:3.11-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501

RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY app.py fluid_advisor.py incident_model.py ./
COPY compliance ./compliance
COPY hydraulikdoc ./hydraulikdoc
COPY db ./db
COPY ops/scripts ./ops/scripts
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY ops/scripts/app-entrypoint.sh /usr/local/bin/app-entrypoint

RUN chmod 0555 /usr/local/bin/app-entrypoint /app/ops/scripts/* && \
    chown -R app:app /app

USER app

EXPOSE 8501

ENTRYPOINT ["/usr/local/bin/app-entrypoint"]
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"]
CMD ["streamlit", "run", "app.py", "--server.enableCORS=true", "--server.enableXsrfProtection=true", "--server.enableWebsocketCompression=false"]
