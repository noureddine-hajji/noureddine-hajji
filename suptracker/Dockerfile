ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SUPTRACKER_DATA=/data PORT=8000

WORKDIR /app
COPY requirements.txt requirements-pipeline.txt ./
RUN pip install --no-cache-dir -r requirements-pipeline.txt

COPY suptracker ./suptracker
COPY scripts ./scripts
COPY docker-entrypoint.sh .

# PREBUILD=1 bakes the SIES data into the image (the build host needs network access to
# data.enseignementsup-recherche.gouv.fr). With PREBUILD=0 the container builds on first start.
ARG PREBUILD=0
RUN mkdir -p /data && if [ "$PREBUILD" = "1" ]; then \
      python -m suptracker.ingest && python -m suptracker.build \
      && python scripts/verify_ground_truth.py --out /data/reports; fi

RUN useradd --system --uid 10001 app && chown -R app /data /app
USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz')"
ENTRYPOINT ["./docker-entrypoint.sh"]
