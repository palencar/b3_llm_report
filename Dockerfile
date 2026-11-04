FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    TZ=UTC

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

COPY requirements.txt requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt \
    && pip check

COPY src/ ./src/
COPY main.py watch_queue.py init_db.py ingest.py ingest_cvm.py build_ticker_map.py ./

RUN mkdir -p data/duckdb data/raw data/snapshots reports queue \
    && chown -R app:app data reports queue

USER app

CMD ["python", "watch_queue.py"]
