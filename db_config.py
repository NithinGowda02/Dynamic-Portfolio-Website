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


def get_database_uri(*, sqlite_fallback_path: str) -> str:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return _normalize_database_url(database_url)
    # Dev-only fallback (do not rely on this in production).
    sqlite_path = os.path.abspath(sqlite_fallback_path)
    # Use forward slashes for SQLite URI compatibility on Windows.
    sqlite_path = sqlite_path.replace("\\", "/")
    return f"sqlite:///{sqlite_path}"

