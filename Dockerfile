FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system atlaspay && adduser --system --ingroup atlaspay atlaspay

COPY pyproject.toml README.md ./
COPY app ./app
COPY migrations ./migrations

RUN pip install .

USER atlaspay

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.getenv('PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2)" || exit 1

CMD ["sh", "-c", "if [ \"${ATLASPAY_DEMO_BOOTSTRAP:-0}\" = \"1\" ]; then python -m app.hosted_demo; fi; exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
