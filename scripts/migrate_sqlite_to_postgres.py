import argparse
import os
import sqlite3

from sqlalchemy import text

import models
from app import DB_PRIMARY_PATH, app
from extensions import db


TABLES_IN_ORDER = [
    ("projects", models.Project),
    ("project_images", models.ProjectImage),
    ("project_thumbnails", models.ProjectThumbnail),
    ("skills", models.Skill),
    ("experience", models.Experience),
    ("certifications", models.Certification),
    ("profile", models.Profile),
    ("about_content", models.AboutContent),
    ("about_intro", models.AboutIntro),
    ("about_interests", models.AboutInterest),
    ("highlights", models.Highlight),
]


def _sqlite_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _copy_table(src: sqlite3.Connection, table: str, model_cls):
    rows = src.execute(f"SELECT * FROM {table}").fetchall()
    for r in rows:
        data = dict(r)
        obj = model_cls(**data)
        db.session.add(obj)


def _truncate_all():
    # Delete children first.
    for _name, model_cls in reversed(TABLES_IN_ORDER):
        db.session.query(model_cls).delete()


def _reset_postgres_sequences():
    if db.engine.dialect.name != "postgresql":
        return

    for table, _model_cls in TABLES_IN_ORDER:
        # Most tables use `id` as PK with a serial/identity.
        db.session.execute(
            text(
                """
                SELECT setval(
                  pg_get_serial_sequence(:t, 'id'),
                  COALESCE((SELECT MAX(id) FROM """ + table + """), 1),
                  true
                )
                """
            ),
            {"t": table},
        )


def main():
    parser = argparse.ArgumentParser(description="Migrate data from SQLite to PostgreSQL (via DATABASE_URL).")
    parser.add_argument("--sqlite", default=DB_PRIMARY_PATH, help="Path to SQLite DB file (default: app DB_PRIMARY_PATH)")
    parser.add_argument("--truncate", action="store_true", help="Delete destination tables before copying")
    args = parser.parse_args()

    sqlite_path = os.path.abspath(args.sqlite)
    if not os.path.exists(sqlite_path):
        raise SystemExit(f"SQLite DB not found: {sqlite_path}")

    src = _sqlite_connect(sqlite_path)

    with app.app_context():
        if args.truncate:
            _truncate_all()
            db.session.commit()

        for table, model_cls in TABLES_IN_ORDER:
            _copy_table(src, table, model_cls)

        db.session.commit()
        _reset_postgres_sequences()
        db.session.commit()

    print("Done.")


if __name__ == "__main__":
    main()

