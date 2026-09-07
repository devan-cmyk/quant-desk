FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    QD_TRADING_MODE=paper \
    QD_ALLOW_LIVE_ENV=0

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY quant_desk ./quant_desk
RUN pip install --no-cache-dir ".[dashboard]"

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8800

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8800}/ >/dev/null || exit 1

CMD ["sh", "-c", "exec uvicorn quant_desk.dashboard.app:app --host 0.0.0.0 --port ${PORT:-8800} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
