# KOL Strategies - Linux image for the VPS (see README "Deploying on the Hostinger VPS").
FROM python:3.12-slim

# the git commit this image was built from (set by the GitHub workflow); shown on the dashboard
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC \
    KOL_DATA_DIR=/app/data \
    DASHBOARD_BIND=0.0.0.0 \
    DASHBOARD_PORT=8030

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kol ./kol
RUN useradd --create-home --uid 1000 kol && mkdir -p /app/data && chown -R kol /app
USER kol

EXPOSE 8030
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8030/healthz', timeout=4)" || exit 1
CMD ["python", "-m", "kol"]
