# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Django-based web application that scrapes NBA news from UDN (聯合報) and serves them via a REST API with a frontend. Uses Django REST Framework, PostgreSQL, and Docker Compose.

## Common Commands

All commands run inside Docker unless noted otherwise:

```bash
# Start/stop services
docker-compose up
docker-compose down

# Run tests
docker-compose exec web python manage.py test

# Run a single test class or method
docker-compose exec web python manage.py test news.tests.NewsAPITestCase
docker-compose exec web python manage.py test news.tests.NewsAPITestCase.test_news_list

# Database migrations
docker-compose exec web python manage.py makemigrations
docker-compose exec web python manage.py migrate

# Run the news scraper
docker-compose exec web python manage.py scrape_news
```

## Architecture

- **`config/`** — Django project settings and root URL routing. PostgreSQL connection configured via environment variables from `.env`.
- **`news/`** — Single Django app containing everything: model, DRF views/serializers, scraper logic, management command, templates, and static files.

### Key data flow

1. **Scraper** (`news/scraper.py`) fetches the 焦點新聞 carousel from UDN NBA, parses articles with BeautifulSoup, and stores them in the `News` model. Deduplication via unique `source_url` constraint.
2. **REST API** (`news/views.py`) exposes `GET /api/news/` (paginated list, excludes `content`) and `GET /api/news/<id>/` (full detail). Page size is 10, configured in `config/settings.py` under `REST_FRAMEWORK`.
3. **Frontend** templates at `/` and `/news/<id>/` use vanilla JS `fetch()` to call the API and render content client-side.

### URL structure

| Path              | Purpose                     |
| ----------------- | --------------------------- |
| `/`               | News list page (template)   |
| `/news/<id>/`     | News detail page (template) |
| `/api/news/`      | DRF list endpoint           |
| `/api/news/<id>/` | DRF detail endpoint         |
| `/admin/`         | Django admin                |

## Docker Setup

- **web**: Python 3.12-slim, Django dev server on port 8000
- **db**: PostgreSQL 16 with health checks
- Environment variables loaded from `.env` (see `.env.example`)

## Implementation Status

Phases 1–6 (scaffold, model, scraper, API, frontend, basic tests) are complete. Phases 7–10 (Celery scheduled tasks, WebSocket notifications, performance optimization, deployment) are not yet implemented. See `docs/implementation-plan.md` for the full roadmap.
