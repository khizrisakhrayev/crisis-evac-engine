# Urban Crisis & Crowd Evacuation Engine - single container (FastAPI + SQLite + static frontend)
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# SQLite file lives in a volume; it is created and seeded on first start.
ENV DATABASE_URL=sqlite:////data/crisis.db
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
