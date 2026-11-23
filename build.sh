#!/usr/bin/env bash
# JanSutra AI — build script used by Render (runs once per deploy).
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Create or refresh the single Administrator / District Collector account.
# Credentials come from the COLLECTOR_USERNAME / COLLECTOR_EMAIL / COLLECTOR_PASSWORD
# environment variables set in the Render dashboard — nothing is hardcoded here.
if [ -n "$COLLECTOR_USERNAME" ] && [ -n "$COLLECTOR_PASSWORD" ]; then
  python manage.py create_collector
else
  echo "Skipped create_collector: set COLLECTOR_USERNAME and COLLECTOR_PASSWORD to create the admin account."
fi
