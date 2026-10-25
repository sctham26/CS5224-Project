FROM ghcr.io/astral-sh/uv:0.13.1 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ARG BACKEND_COMMIT
LABEL org.opencontainers.image.revision=$BACKEND_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && mkdir -p /opt/spip-cloud \
    && curl -fsS https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem -o /opt/spip-cloud/rds-ca.pem \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY .cloud/requirements.lock /tmp/requirements.lock
RUN uv pip install --system --require-hashes -r /tmp/requirements.lock
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY data/cleaned/public_esg_baseline.csv ./data/cleaned/public_esg_baseline.csv
COPY .cloud/entrypoint.py .cloud/operations.py /opt/spip-cloud/
RUN useradd --uid 10001 --create-home spip
USER spip
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
