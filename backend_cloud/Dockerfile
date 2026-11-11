FROM ghcr.io/astral-sh/uv:0.13.1 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --show-error --silent https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /tmp/rds-ca.pem \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/spip-cloud
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY bootstrap.py entrypoint.py ./
RUN mv /tmp/rds-ca.pem /opt/spip-cloud/rds-ca.pem && useradd --uid 10001 --create-home spip
USER spip
ENV PATH="/opt/spip-cloud/.venv/bin:$PATH"
CMD ["python", "bootstrap.py"]
