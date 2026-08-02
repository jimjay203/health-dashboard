#!/bin/bash
echo "🚀 Starte Deployment..."
git pull origin main
docker compose down
docker compose up -d --build
echo "✅ Deployment erfolgreich abgeschlossen!"
