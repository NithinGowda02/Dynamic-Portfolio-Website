import os

def get_database_uri():
    db_url = os.getenv("DATABASE_URL")

    if not db_url:
        raise Exception("❌ DATABASE_URL is not set in environment")

    # Fix for Render PostgreSQL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    return db_url