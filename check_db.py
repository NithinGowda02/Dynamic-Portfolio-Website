"""
check_db.py — run manually to verify your Neon Postgres connection.

Usage (locally or via Render Shell):
    python check_db.py

It will print every table name and row count so you can confirm the DB
is reachable and the schema has been created correctly.

Your Neon DATABASE_URL should look like:
    postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require
"""

import os
import sys


def main() -> None:
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        print("❌  DATABASE_URL is not set. Cannot connect.")
        print("    Set it to your Neon connection string, e.g.:")
        print("    postgresql://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require")
        sys.exit(1)

    # Handle legacy postgres:// prefix (Neon uses postgresql:// natively)
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # Ensure sslmode=require is present
    if "sslmode" not in db_url:
        separator = "&" if "?" in db_url else "?"
        db_url = f"{db_url}{separator}sslmode=require"

    try:
        import sqlalchemy as sa
    except ImportError:
        print("❌  SQLAlchemy is not installed (pip install sqlalchemy).")
        sys.exit(1)

    try:
        engine = sa.create_engine(
            db_url,
            connect_args={"sslmode": "require"},
            pool_pre_ping=True,
        )
        with engine.connect() as conn:
            # List every table in the public schema
            result = conn.execute(sa.text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            ))
            tables = [row[0] for row in result]

            if not tables:
                print("⚠️   Connected to Neon successfully but no tables found yet.")
                print("     Run the app once (AUTO_DB_CREATE=true) to create the schema.")
                return

            print(f"✅  Connected to Neon Postgres. Found {len(tables)} table(s):\n")
            for table in tables:
                count_row = conn.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"'))
                count = count_row.scalar()
                print(f"    {table:<30} {count:>6} row(s)")

            print("\nAll tables are reachable. Your Neon database is working correctly.")

    except Exception as exc:
        print(f"❌  Connection failed: {exc}")
        print("\n    Common fixes:")
        print("    1. Make sure DATABASE_URL ends with ?sslmode=require")
        print("    2. Check your Neon project is not suspended (free tier sleeps after inactivity)")
        print("    3. Verify the connection string in your Neon dashboard → Connection Details")
        sys.exit(1)


if __name__ == "__main__":
    main()