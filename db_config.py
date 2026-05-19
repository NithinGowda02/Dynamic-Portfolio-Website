import os


def get_database_uri() -> str:
    db_url = os.getenv("DATABASE_URL", "").strip()

    if not db_url:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Add it as an environment variable "
            "(use the connection string from your Neon dashboard — "
            "it should look like: postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require)."
        )

    # Neon uses postgresql:// natively, but handle legacy postgres:// just in case
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # Ensure sslmode=require is present (required by Neon)
    if "sslmode" not in db_url:
        separator = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{separator}sslmode=require"

    return db_url