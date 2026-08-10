FROM python:3.11-slim

RUN rm -rf /var/lib/apt/lists/* \
    && apt-get update -o Acquire::By-Hash=no -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

COPY . .

EXPOSE 5000

# One worker process keeps the Whisper model and transcript state in a single
# place. Threads must be generous: /proxy holds a thread for as long as a
# station is playing, so a small pool starves API calls like /start and the
# station switch never gets served.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "32", "--timeout", "300", "app:app"]
