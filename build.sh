#!/usr/bin/env bash
# Lo ejecuta Render en cada publicación.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py createcachetable
