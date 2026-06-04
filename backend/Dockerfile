FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ALLOW_FAKE_TEST_UPLOADS=false
ENV MALWARE_SCAN_ENABLED=false

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend

ENV PORT=5050
EXPOSE 5050

CMD ["gunicorn", "-b", "0.0.0.0:5050", "--timeout", "120", "--workers", "2", "--threads", "2", "backend.app:app"]
