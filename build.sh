#!/usr/bin/env bash
# Render build script. Set this as the "Build Command" for the web service
# (or Render will pick it up automatically if left as the default).
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate
