# Multi-Stage-Build: Stage 1 baut das React/Vite-Frontend, Stage 2 ist das eigentliche
# FastAPI-Backend, das die gebauten Frontend-Dateien selbst über StaticFiles ausliefert
# (kein separater Nginx-Container). Build-Context ist der Repo-Root (siehe docker-compose.yml
# "context: ."), damit db.py aus dem Root mit in dieses Image kopiert werden kann.

FROM node:20-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Alle Root-Level-Module (db.py, garmin_auth.py, garmin_service.py, auto_sync.py, ...) werden
# unverändert aus dem Repo-Root übernommen (nicht Teil von backend/) und landen direkt neben
# main.py, damit z.B. "from db import get_connection" ohne jede Anpassung funktioniert. Bewusst
# "*.py" statt einzelner Dateien - robuster gegenüber wachsenden Abhängigkeiten zwischen den
# Modulen (aktuell ungenutzte Dateien wie app.py/chat_engine.py landen dabei inert mit im Image,
# das ist unkritisch). pages/, examples/, backend/, frontend/ werden dadurch NICHT mitkopiert.
COPY *.py .
COPY backend/ .
COPY --from=frontend-build /frontend/dist ./static

EXPOSE 8000

HEALTHCHECK CMD curl --fail http://localhost:8000/api/health || exit 1

ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
