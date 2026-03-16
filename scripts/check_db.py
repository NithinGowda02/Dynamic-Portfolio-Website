"""
Quick DB inspection helper (not used by the Flask app at runtime).
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", os.environ.get("PORTFOLIO_DB", "portfolio.db"))

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print("DB:", DB_PATH)
print("Tables:")
for t in tables:
    print("-", t)
conn.close()
