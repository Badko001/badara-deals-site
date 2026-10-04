FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY backend/app ./app
COPY data/mock /srv/data/mock

# Non-root user; database lives in a volume.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /srv/data /srv/browser/screenshots \
    && chown -R agent:agent /srv
USER agent

ENV DATABASE_URL=sqlite:////srv/data/air_upgrade_agent.db \
    SCREENSHOT_DIR=/srv/browser/screenshots \
    BROWSER_HEADLESS=true
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
