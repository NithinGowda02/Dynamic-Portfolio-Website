import os


def get_database_uri() -> str:
    db_url = os.getenv("DATABASE_URL", "").strip()

    if not db_url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Add it as an environment variable in your Render dashboard "
            "(it is auto-populated when you attach a Render Postgres database)."
        )

    # Render (and older Heroku) emit postgres:// but SQLAlchemy 1.4+ requires postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    return db_url