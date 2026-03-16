"""
Legacy entrypoint kept for convenience.

Professional layout uses: scripts/check_db.py
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "scripts" / "check_db.py"), run_name="__main__")
