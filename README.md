# Nithin.dev Portfolio (Flask + PostgreSQL + Cloudinary)

Dynamic developer portfolio built with Flask + SQLAlchemy.

## Production Persistence (Render)

Render’s filesystem is ephemeral, so this app is configured to be fully dynamic using:

- PostgreSQL for all data (`DATABASE_URL`)
- Cloudinary for all uploaded files/images (`CLOUDINARY_URL`)

No local database files are used, and uploads are not written to disk.

## Render Settings

- Environment: Python
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT`

## Required Environment Variables (Render Web Service)

- `SECRET_KEY` (or `FLASK_SECRET`): long random string
- `DATABASE_URL`: PostgreSQL connection string
- `CLOUDINARY_URL`: `cloudinary://<api_key>:<api_secret>@<cloud_name>`
- `TRUST_PROXY_HEADERS=true` (recommended)

## Database Schema

This repo includes Flask-Migrate support. Recommended flow:

- `flask db init` (one time per repo)
- `flask db migrate -m "init"`
- `flask db upgrade`

If you are bootstrapping a brand-new environment quickly, you can allow auto table creation by setting:

- `AUTO_DB_CREATE=true`
