# Production image with ffmpeg (required for Telegram OGG/Opus -> MP3 before Whisper)
FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
# Ensure logs appear immediately in Railway "Deploy" / runtime logs (no stdout buffering)
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Use exec JSON form so a shell expands $PORT at container start.
# (Railway UI "Start Command" like `uvicorn ... --port $PORT` without sh often passes literal "$PORT" -> 502.)
# If Railway overrides CMD, clear Custom Start Command or wrap with sh -c "... ${PORT:-8000} ...".
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --log-level info --access-log"]
