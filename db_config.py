import os


def _normalize_database_url(url: str) -> str:
    """
    Render (and some other providers) historically expose Postgres URLs as `postgres://...`
    but SQLAlchemy expects `postgresql://...`.
    """
    u = (url or "").strip()
    if u.startswith("postgres://"):
        return "postgresql://" + u[len("postgres://") :]
    return u


def get_database_uri() -> str:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required. This app no longer supports local database files; "
            "configure PostgreSQL and set DATABASE_URL."
        )
    return _normalize_database_url(database_url)
