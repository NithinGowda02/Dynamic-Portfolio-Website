"""
Legacy entrypoint kept for convenience.

Professional layout uses: scripts/verify_project.py
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "scripts" / "verify_project.py"), run_name="__main__")
