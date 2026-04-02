#!/bin/bash
set -e

# Only run Django setup steps for the web service
if [ "$1" = "gunicorn" ]; then
    echo "Applying database migrations..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput

    echo "Running news scraper..."
    python manage.py scrape_news
fi

exec "$@"
