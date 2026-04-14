"""
check_db.py — run manually to verify your Render Postgres connection.

Usage (locally or via Render Shell):
    python check_db.py

It will print every table name and row count so you can confirm the DB
is reachable and the schema has been created correctly.
"""

import os
import sys


def main() -> None:
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        print("❌  DATABASE_URL is not set. Cannot connect.")
        sys.exit(1)

    # Render emits postgres:// but psycopg2/SQLAlchemy need postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

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
                print("⚠️   Connected successfully but no tables found yet.")
                print("     Run the app once with AUTO_DB_CREATE=true to create the schema.")
                return

            print(f"✅  Connected to Postgres. Found {len(tables)} table(s):\n")
            for table in tables:
                count_row = conn.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"'))
                count = count_row.scalar()
                print(f"    {table:<30} {count:>6} row(s)")

            print("\nAll tables are reachable. Your database is working correctly.")

    except Exception as exc:
        print(f"❌  Connection failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()