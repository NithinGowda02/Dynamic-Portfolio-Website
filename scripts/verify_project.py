import io
import os
import sys
from typing import Iterable, Tuple

from pathlib import Path

# Allow running this file directly from ./scripts on Windows.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _png_1x1_bytes() -> bytes:
    # Valid 1x1 transparent PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc`\x00"
        b"\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _pdf_minimal_bytes() -> bytes:
    # Minimal-ish PDF bytes: enough for download/view tests where we only validate routing.
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0>>endobj\n%%EOF\n"


def _ok(label: str) -> None:
    print(f"[OK] {label}")


def _fail(label: str, detail: str = "") -> None:
    msg = f"[FAIL] {label}"
    if detail:
        msg += f": {detail}"
    print(msg)
    raise SystemExit(1)


def _check_status(client, path: str, expected: Iterable[int] = (200,)) -> bytes:
    resp = client.get(path)
    if resp.status_code not in expected:
        snippet = resp.get_data(as_text=True)[:600]
        _fail(f"GET {path}", f"status={resp.status_code}; body_snippet={snippet!r}")
    return resp.data


def _login_admin(client, username: str = "admin", password: str = "admin123") -> None:
    resp = client.post(
        "/admin/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )
    if resp.status_code != 200:
        _fail("admin login", f"status={resp.status_code}")
    if b"Admin Dashboard" not in resp.data:
        # Template encoding can vary; keep it a soft check.
        if b"Manage your portfolio content" not in resp.data:
            _fail("admin login", "did not reach admin dashboard")
    _ok("Admin login")


def _db_counts(db_connect_fn) -> Tuple[int, int, int, int]:
    conn = db_connect_fn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM projects")
    projects = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM project_images")
    project_images = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM skills")
    skills = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM certifications")
    certs = int(cur.fetchone()[0])
    conn.close()
    return projects, project_images, skills, certs


def main() -> int:
    # Avoid creating __pycache__ (this workspace can be permission-restricted on Windows).
    sys.dont_write_bytecode = True

    import importlib

    mod = importlib.import_module("app")
    flask_app = mod.app
    flask_app.testing = True

    db_primary = getattr(mod, "DB_PRIMARY_PATH", "")
    db_fallback = getattr(mod, "DB_FALLBACK_PATH", "")
    if not db_primary or not os.path.exists(db_primary):
        _fail("DB path", f"DB_PRIMARY_PATH missing or not found: {db_primary!r}")
    # The app may fall back at runtime if the primary DB is stuck with a locked journal.
    if db_fallback and os.path.exists(db_fallback):
        _ok(f"DB primary exists at {db_primary} (fallback available: {db_fallback})")
    else:
        _ok(f"DB exists at {db_primary}")

    client = flask_app.test_client()

    # Public pages
    _check_status(client, "/")
    _ok("Home page loads")
    _check_status(client, "/about")
    _ok("About page loads")
    _check_status(client, "/projects")
    _ok("Projects page loads")
    _check_status(client, "/skills")
    _ok("Skills page loads")
    _check_status(client, "/experience")
    _ok("Experience page loads")
    _check_status(client, "/certifications")
    _ok("Certifications page loads")
    _check_status(client, "/contact")
    _ok("Contact page loads")

    # Static assets
    _check_status(client, "/static/css/style.css")
    _check_status(client, "/static/js/main.js")
    _ok("Static CSS/JS load")

    # Admin
    _check_status(client, "/admin/login")
    _ok("Admin login page loads")
    _login_admin(client)

    before = _db_counts(mod.db_connect)

    # Add a project with multiple images (2 here; route supports up to 6).
    img1 = (io.BytesIO(_png_1x1_bytes()), "shot1.png")
    img2 = (io.BytesIO(_png_1x1_bytes()), "shot2.png")
    resp = client.post(
        "/admin/projects",
        data={
            "title": "Verify Project",
            "description": "Verify multi-image upload + slider.",
            "tech_stack": "Flask,SQLite",
            "github_link": "https://example.com",
            "live_demo": "https://example.com",
            "project_images": [img1, img2],
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    if resp.status_code != 200:
        _fail("Add project (admin)", f"status={resp.status_code}")
    _ok("Add project (multi-image)")

    # Add a skill
    resp = client.post("/admin/skills", data={"skill_name": "VerifySkill"}, follow_redirects=True)
    if resp.status_code != 200:
        _fail("Add skill (admin)", f"status={resp.status_code}")
    _ok("Add skill")

    # Add an experience entry
    resp = client.post(
        "/admin/experience",
        data={
            "role": "Verify Role",
            "organization": "Verify Org",
            "duration": "2026",
            "description": "Verify experience add.",
        },
        follow_redirects=True,
    )
    if resp.status_code != 200:
        _fail("Add experience (admin)", f"status={resp.status_code}")
    _ok("Add experience")

    # Add a certification PDF
    pdf = (io.BytesIO(_pdf_minimal_bytes()), "verify.pdf")
    resp = client.post(
        "/admin/certifications",
        data={"title": "Verify Cert", "platform": "Verify", "year": "2026", "certificate": pdf},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    if resp.status_code != 200:
        _fail("Add certification (admin)", f"status={resp.status_code}")
    _ok("Add certification")

    after = _db_counts(mod.db_connect)
    if after[0] <= before[0] or after[1] <= before[1]:
        _fail("DB project insert", f"projects/images did not increase. before={before}, after={after}")
    if after[2] <= before[2]:
        _fail("DB skill insert", f"skills did not increase. before={before}, after={after}")
    if after[3] <= before[3]:
        _fail("DB cert insert", f"certs did not increase. before={before}, after={after}")
    _ok("Database inserts verified")

    # Verify the project renders on both home and projects pages.
    home_html = _check_status(client, "/").decode("utf-8", errors="replace")
    if "Verify Project" not in home_html:
        _fail("Home project render", "new project title not found on home")
    _ok("Home shows new project")

    projects_html = _check_status(client, "/projects").decode("utf-8", errors="replace")
    if "Verify Project" not in projects_html:
        _fail("Projects page render", "new project title not found on projects page")
    if "proj-gallery__thumbs" not in projects_html:
        _fail("Projects thumbnails render", "thumbnail strip markup not found")
    _ok("Projects page shows gallery + thumbnails")

    # Cleanup: remove the test records/files so this script is safe to run on a real portfolio DB.
    # Set VERIFY_KEEP=1 to keep inserted test data.
    if os.environ.get("VERIFY_KEEP", "").strip() != "1":
        try:
            conn = mod.db_connect()
            cur = conn.cursor()

            cur.execute("SELECT id FROM projects WHERE title = ?", ("Verify Project",))
            proj_ids = [r[0] for r in (cur.fetchall() or []) if r and r[0] is not None]

            cur.execute("SELECT certificate_file FROM certifications WHERE title = ?", ("Verify Cert",))
            cert_files = [r[0] for r in (cur.fetchall() or []) if r and r[0]]

            if proj_ids:
                cur.execute(
                    f"DELETE FROM project_images WHERE project_id IN ({','.join('?' for _ in proj_ids)})",
                    tuple(proj_ids),
                )
                cur.execute(
                    f"DELETE FROM projects WHERE id IN ({','.join('?' for _ in proj_ids)})",
                    tuple(proj_ids),
                )

            cur.execute("DELETE FROM skills WHERE skill_name = ?", ("VerifySkill",))
            cur.execute("DELETE FROM experience WHERE role = ? AND organization = ?", ("Verify Role", "Verify Org"))
            cur.execute("DELETE FROM certifications WHERE title = ?", ("Verify Cert",))

            conn.commit()
            conn.close()

            # Best-effort file cleanup (ignore failures).
            import shutil

            for pid in proj_ids:
                folder = os.path.join(mod.UPLOAD_PROJECTS_NEW, f"project_{pid}")
                try:
                    if os.path.isdir(folder):
                        shutil.rmtree(folder, ignore_errors=True)
                except Exception:
                    pass

            for cf in cert_files:
                try:
                    p = os.path.join(mod.UPLOAD_CERTIFICATES, cf)
                    if os.path.isfile(p):
                        os.remove(p)
                except Exception:
                    pass

            _ok("Cleanup completed (test records removed)")
        except Exception as exc:
            print(f"[WARN] Cleanup failed (non-fatal): {exc}")

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
