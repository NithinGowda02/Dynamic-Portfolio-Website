import os
import sqlite3
from datetime import datetime
from typing import Optional

from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from db_config import get_database_uri
from extensions import db, migrate

# ---------------------------------------------------------------------------
# Cloudinary – optional cloud storage backend.
# Set CLOUDINARY_URL  (e.g. cloudinary://api_key:api_secret@cloud_name)
# OR set the three separate env vars below.
# When these are absent the app falls back to local disk (same as before).
# ---------------------------------------------------------------------------
try:
    import cloudinary
    import cloudinary.uploader

    # Let Cloudinary parse CLOUDINARY_URL automatically first.
    cloudinary.config(secure=True)

    # If discrete env vars are provided, they should override CLOUDINARY_URL.
    _cld_overrides = {}
    _cld_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    _cld_key = os.environ.get("CLOUDINARY_API_KEY")
    _cld_secret = os.environ.get("CLOUDINARY_API_SECRET")
    if _cld_name:
        _cld_overrides["cloud_name"] = _cld_name
    if _cld_key:
        _cld_overrides["api_key"] = _cld_key
    if _cld_secret:
        _cld_overrides["api_secret"] = _cld_secret
    if _cld_overrides:
        cloudinary.config(**_cld_overrides)

    _CLOUDINARY_ENABLED = bool(
        cloudinary.config().cloud_name
        and cloudinary.config().api_key
        and cloudinary.config().api_secret
    )
except ImportError:
    _CLOUDINARY_ENABLED = False


def _cloudinary_upload(file_obj, folder: str, resource_type: str = "auto") -> Optional[str]:
    """Upload *file_obj* to Cloudinary and return the secure URL, or None on failure."""
    if not _CLOUDINARY_ENABLED:
        return None
    try:
        result = cloudinary.uploader.upload(
            file_obj,
            folder=folder,
            resource_type=resource_type,
            overwrite=True,
        )
        return result.get("secure_url")
    except Exception as exc:
        print(f"[WARN] Cloudinary upload failed: {exc}")
        return None


def _cloudinary_delete(url_or_path: str) -> None:
    """Best-effort delete from Cloudinary given a stored URL or public_id."""
    if not _CLOUDINARY_ENABLED or not url_or_path:
        return
    if not url_or_path.startswith("http"):
        return  # local file – nothing to do in Cloudinary
    try:
        # Extract public_id: everything between /upload/ and the file extension.
        import re
        match = re.search(r"/upload/(?:v\d+/)?(.+?)(?:\.[^.]+)?$", url_or_path)
        if match:
            public_id = match.group(1)
            cloudinary.uploader.destroy(public_id, resource_type="raw")
            cloudinary.uploader.destroy(public_id, resource_type="image")
    except Exception as exc:
        print(f"[WARN] Cloudinary delete failed: {exc}")


def _is_url(value: str) -> bool:
    return bool(value and value.startswith("http"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY") or os.environ.get("FLASK_SECRET", "dev-secret")
# When deployed behind a reverse proxy (e.g., Render), trust forwarded headers so redirects and
# URL generation use the correct scheme/host. Keep this opt-in for safety.
_trust_proxy = os.environ.get("TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes"}
if _trust_proxy or os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
# Ensure mobile/production browsers pick up CSS/JS updates quickly.
# Many hosts/CDNs can be aggressive about caching `/static/*` files.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

@app.after_request
def _add_static_cache_headers(response):
    try:
        path = request.path or ""
    except Exception:
        path = ""

    if path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Admin credentials (in production, store securely)
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD_HASH = generate_password_hash('admin123')  # Change this password!

def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def _resolve_storage_root():
    """
    Storage root for mutable data (SQLite DB + user uploads).

    On Render and similar platforms, the filesystem is ephemeral across deploys unless you mount a
    persistent disk. Point PORTFOLIO_STORAGE_DIR at that mount path (e.g., /var/data) so content
    added from the admin dashboard survives redeploys.
    """
    root = os.environ.get("PORTFOLIO_STORAGE_DIR", "").strip()
    if not root:
        return BASE_DIR
    if os.path.isabs(root):
        return os.path.abspath(root)
    return os.path.abspath(os.path.join(BASE_DIR, root))


STORAGE_ROOT = _resolve_storage_root()

# Prefer a clean, writable DB file. Keep it out of /static and /uploads.
DATA_DIR = os.path.join(STORAGE_ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PRIMARY_PATH = os.path.join(DATA_DIR, os.environ.get("PORTFOLIO_DB", "portfolio.db"))
# Legacy location used by older versions of the app.
DB_LEGACY_PATH = os.path.join(BASE_DIR, "portfolio.db")
# If the primary DB is left with a locked hot-journal (common on Windows when a process crashes or holds the file),
# SQLite can start throwing "disk I/O error" on open. Keep a fallback copy that we can switch to automatically.
DB_FALLBACK_PATH = os.path.join(DATA_DIR, "portfolio_live.db")
UPLOADS_ROOT = os.path.join(STORAGE_ROOT, "uploads")
UPLOAD_CERTIFICATES = os.path.join(UPLOADS_ROOT, "certificates")
UPLOAD_PROJECTS_NEW = os.path.join(UPLOADS_ROOT, "projects")
# Legacy flat folder used by older versions of the app.
UPLOAD_PROJECTS_LEGACY = os.path.join(UPLOADS_ROOT, "project_images")
UPLOAD_PROJECT_THUMBNAILS = os.path.join(UPLOADS_ROOT, "project_thumbnails")
UPLOAD_PROFILE = os.path.join(UPLOADS_ROOT, "profile")
UPLOAD_ABOUT = os.path.join(UPLOADS_ROOT, "about")
UPLOAD_RESUME = os.path.join(UPLOADS_ROOT, "resume")
UPLOAD_EXPERIENCE = os.path.join(UPLOADS_ROOT, "experience")

ALLOWED_EXTENSIONS_PDF = {"pdf"}
ALLOWED_EXTENSIONS_IMG = {"png", "jpg", "jpeg", "gif", "svg"}

for folder in [
    UPLOAD_CERTIFICATES,
    UPLOAD_PROJECTS_NEW,
    UPLOAD_PROJECTS_LEGACY,
    UPLOAD_PROJECT_THUMBNAILS,
    UPLOAD_PROFILE,
    UPLOAD_ABOUT,
    UPLOAD_RESUME,
    UPLOAD_EXPERIENCE,
]:
    os.makedirs(folder, exist_ok=True)


# ---------------------------------------------------------------------------
# Database (production: PostgreSQL via DATABASE_URL; dev fallback: local SQLite)
# ---------------------------------------------------------------------------
app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri(sqlite_fallback_path=DB_PRIMARY_PATH)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
migrate.init_app(app, db)

# Register ORM models for Flask-Migrate / SQLAlchemy.
import models  # noqa: E402

_USING_EXTERNAL_DB = bool(os.environ.get("DATABASE_URL", "").strip())
_AUTO_DB_CREATE = os.environ.get("AUTO_DB_CREATE", "").strip().lower() in {"1", "true", "yes"}
if not _USING_EXTERNAL_DB:
    # Local development convenience: auto-create tables for the SQLite fallback.
    _AUTO_DB_CREATE = True

if _AUTO_DB_CREATE:
    with app.app_context():
        db.create_all()
        # Ensure singleton rows exist (mirrors the old SQLite bootstrapping logic).
        from models import AboutContent, AboutIntro  # noqa: E402

        if db.session.get(AboutContent, 1) is None:
            db.session.add(AboutContent(id=1, preview_text="", details_text=""))
        if db.session.get(AboutIntro, 1) is None:
            db.session.add(AboutIntro(id=1, headline="", role_line="", short_desc="", about_image=""))
        db.session.commit()


def db_connect():
    """
    Connect to the primary DB and apply pragmas that avoid creating *-journal files.
    """
    def _connect_and_probe(path):
        conn = sqlite3.connect(path, timeout=5)
        try:
            # Avoid creating any *-journal files (some Windows setups lock them aggressively).
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.OperationalError:
            # Read-only connections may reject PRAGMA writes.
            pass
        # Some failures only show up when the first query runs (e.g. locked journal / disk I/O).
        cur = conn.cursor()
        cur.execute("PRAGMA schema_version")
        cur.fetchone()
        return conn

    try:
        return _connect_and_probe(DB_PRIMARY_PATH)
    except sqlite3.OperationalError as exc:
        # Self-heal: if the primary DB is in a bad journal state (locked/permission denied),
        # fall back to a copied DB file so the site keeps working.
        msg = str(exc).lower()
        if "disk i/o" not in msg and "i/o error" not in msg:
            raise

        try:
            if not os.path.exists(DB_FALLBACK_PATH) and os.path.exists(DB_PRIMARY_PATH):
                # Best-effort copy; ignore journals and just duplicate the main DB file.
                with open(DB_PRIMARY_PATH, "rb") as src, open(DB_FALLBACK_PATH, "wb") as dst:
                    dst.write(src.read())
        except OSError:
            # If copying fails, still try opening fallback if it exists.
            pass

        if os.path.exists(DB_FALLBACK_PATH):
            return _connect_and_probe(DB_FALLBACK_PATH)

        # Nothing to fall back to; re-raise the original error.
        raise


def allowed_file(filename, allowed_ext):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_ext


@app.context_processor
def inject_static_version():
    """
    Cache-bust static assets so browsers pick up CSS/JS changes immediately.
    This helps when you edit the footer but the browser keeps an old cached stylesheet.
    """
    try:
        css_path = os.path.join(app.static_folder, "css", "style.css")
        anim_path = os.path.join(app.static_folder, "css", "animations.css")
        js_path = os.path.join(app.static_folder, "js", "main.js")
        mtimes = [os.path.getmtime(css_path), os.path.getmtime(js_path)]
        if os.path.exists(anim_path):
            mtimes.append(os.path.getmtime(anim_path))
        v = int(max(mtimes))
    except OSError:
        v = 1
    return {"static_v": v}


@app.context_processor
def inject_file_url():
    def file_url(value, route, **kwargs):
        """Return a direct URL if value is already a cloud URL, else use url_for."""
        if not value:
            return ""
        if value.startswith("http"):
            return value
        return url_for(route, filename=value, **kwargs)
    return {"file_url": file_url}

# CREATE DATABASE TABLE
def init_db():
    conn = db_connect()
    cursor = conn.cursor()

    def _ensure_column(table, column, col_def):
        # SQLite doesn't support ADD COLUMN IF NOT EXISTS.
        cursor.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in cursor.fetchall()}
        if column not in cols:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projects(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    description TEXT,
    tech_stack TEXT,
    github_link TEXT,
    project_image TEXT,
    live_demo TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_images(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    image_file TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_thumbnails(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    image_file TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS skills(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS experience(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT,
    organization TEXT,
    duration TEXT,
    description TEXT,
    experience_file TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS certifications(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    platform TEXT,
    year TEXT,
    certificate_file TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS profile(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    title TEXT,
    about TEXT,
    email TEXT,
    github TEXT,
    linkedin TEXT,
    resume_file TEXT,
    profile_image TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS about_content(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    preview_text TEXT,
    details_text TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS about_intro(
    id INTEGER PRIMARY KEY CHECK (id = 1),
    headline TEXT,
    role_line TEXT,
    short_desc TEXT,
    about_image TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS about_interests(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,
    count_value INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS highlights(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    icon_key TEXT,
    title TEXT,
    description TEXT,
    sort_order INTEGER DEFAULT 0
    )
    """)

    # Ensure we always have one about row to update.
    cursor.execute("INSERT OR IGNORE INTO about_content (id, preview_text, details_text) VALUES (1, '', '')")

    # Backfill schema for older DBs.
    try:
        _ensure_column("about_intro", "about_image", "TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        _ensure_column("experience", "experience_file", "TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute(
        "INSERT OR IGNORE INTO about_intro (id, headline, role_line, short_desc, about_image) VALUES (1, '', '', '', '')"
    )

    # If an older DB exists at the legacy path, migrate project-related tables into the new primary DB
    # when the primary DB has no projects yet. This prevents "0 Projects" and empty Projects pages
    # after upgrading the app's DB location.
    try:
        if os.path.exists(DB_LEGACY_PATH) and os.path.abspath(DB_LEGACY_PATH) != os.path.abspath(DB_PRIMARY_PATH):
            cursor.execute("SELECT COUNT(*) FROM projects")
            primary_projects = cursor.fetchone()[0]
            if primary_projects == 0:
                cursor.execute("ATTACH DATABASE ? AS legacy", (DB_LEGACY_PATH,))
                try:
                    cursor.execute("SELECT 1 FROM legacy.sqlite_master WHERE type='table' AND name='projects' LIMIT 1")
                    if cursor.fetchone():
                        cursor.execute("SELECT COUNT(*) FROM legacy.projects")
                        legacy_projects = cursor.fetchone()[0]
                        if legacy_projects > 0:
                            for table in ("projects", "project_images", "project_thumbnails"):
                                cursor.execute(
                                    "SELECT 1 FROM legacy.sqlite_master WHERE type='table' AND name=? LIMIT 1",
                                    (table,),
                                )
                                if not cursor.fetchone():
                                    continue

                                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                                if cursor.fetchone()[0] != 0:
                                    continue

                                cursor.execute(f"PRAGMA table_info({table})")
                                main_cols = [r[1] for r in cursor.fetchall()]
                                cursor.execute(f"PRAGMA legacy.table_info({table})")
                                legacy_cols = {r[1] for r in cursor.fetchall()}
                                cols = [c for c in main_cols if c in legacy_cols]
                                if not cols:
                                    continue

                                col_list = ", ".join(cols)
                                cursor.execute(
                                    f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM legacy.{table}"
                                )

                                # Keep AUTOINCREMENT sequences consistent after inserting explicit ids.
                                try:
                                    cursor.execute(
                                        "INSERT OR IGNORE INTO sqlite_sequence(name, seq) VALUES (?, 0)",
                                        (table,),
                                    )
                                    cursor.execute(
                                        f"UPDATE sqlite_sequence SET seq=(SELECT COALESCE(MAX(id),0) FROM {table}) WHERE name=?",
                                        (table,),
                                    )
                                except sqlite3.OperationalError:
                                    pass
                finally:
                    try:
                        cursor.execute("DETACH DATABASE legacy")
                    except sqlite3.OperationalError:
                        pass
    except sqlite3.OperationalError:
        # Migration is best-effort; ignore if legacy DB is locked/unreadable.
        pass

    conn.commit()
    conn.close()

_LEGACY_SQLITE_BOOTSTRAP = os.environ.get("LEGACY_SQLITE_BOOTSTRAP", "").strip().lower() in {"1", "true", "yes"}
if _LEGACY_SQLITE_BOOTSTRAP:
    # One-time helper for older dev DBs. Prefer Flask-Migrate in all environments.
    try:
        init_db()
    except sqlite3.OperationalError as exc:
        print(f"[WARN] LEGACY_SQLITE_BOOTSTRAP init_db() failed: {exc}")


# GET PROJECTS
def get_projects():
    projects = []
    for p in models.Project.query.order_by(models.Project.id.desc()).all():
        images = [img.image_file or "" for img in (p.images or []) if img and img.image_file]
        cover_image = (p.project_image or "").strip() or (images[0] if images else "")
        projects.append(
            {
                "id": p.id,
                "title": (p.title or "").strip(),
                "description": (p.description or "").strip(),
                "tech_stack": (p.tech_stack or "").strip(),
                "github_link": (p.github_link or "").strip(),
                "live_demo": (p.live_demo or "").strip(),
                "cover_image": cover_image,
                "images": images,
            }
        )
    return projects


# GET CERTIFICATIONS
def get_certifications():
    rows = (
        models.Certification.query.order_by(models.Certification.year.desc(), models.Certification.id.desc()).all()
    )
    return [(c.id, c.title, c.platform, c.year, c.certificate_file) for c in rows]


# GET SKILLS
def get_skills():
    rows = models.Skill.query.order_by(models.Skill.id.asc()).all()
    return [(s.id, s.skill_name) for s in rows]


# GET EXPERIENCE
def get_experience():
    rows = models.Experience.query.order_by(models.Experience.id.asc()).all()
    return [(e.id, e.role, e.organization, e.duration, e.description, e.experience_file) for e in rows]


# GET PROFILE
def get_profile():
    row = models.Profile.query.order_by(models.Profile.id.asc()).first()
    if not row:
        return None
    return (
        row.id,
        row.name,
        row.title,
        row.about,
        row.email,
        row.github,
        row.linkedin,
        row.resume_file,
        row.profile_image,
    )


def get_about_content():
    row = db.session.get(models.AboutContent, 1)
    preview_text = row.preview_text if row and row.preview_text else ""
    details_text = row.details_text if row and row.details_text else ""
    return {"preview_text": preview_text, "details_text": details_text}


def get_about_intro():
    row = db.session.get(models.AboutIntro, 1)
    return {
        "headline": row.headline if row and row.headline else "",
        "role_line": row.role_line if row and row.role_line else "",
        "short_desc": row.short_desc if row and row.short_desc else "",
        "about_image": row.about_image if row and row.about_image else "",
    }


def get_about_interests():
    rows = (
        models.AboutInterest.query.order_by(models.AboutInterest.sort_order.asc(), models.AboutInterest.id.asc()).all()
    )
    return [(r.id, r.label, r.count_value) for r in rows]


def get_highlights():
    rows = models.Highlight.query.order_by(models.Highlight.sort_order.asc(), models.Highlight.id.asc()).all()
    return [(r.id, r.icon_key, r.title, r.description) for r in rows]


def get_stats_counts():
    projects_count = models.Project.query.count()
    skills_count = models.Skill.query.count()
    certifications_count = models.Certification.query.count()
    return {
        "projects": projects_count,
        "skills": skills_count,
        "certifications": certifications_count,
    }


def get_project_thumbnails():
    rows = (
        models.ProjectThumbnail.query.order_by(
            models.ProjectThumbnail.sort_order.asc(), models.ProjectThumbnail.id.asc()
        ).all()
    )
    return [{"id": r.id, "title": (r.title or ""), "image_file": (r.image_file or "")} for r in rows]


@app.route("/")
def home():
    projects = get_projects()
    project_thumbnails = get_project_thumbnails()
    certifications = get_certifications()
    skills = get_skills()
    experience = get_experience()
    profile = get_profile()
    about_content = get_about_content()
    about_intro = get_about_intro()
    about_interests = get_about_interests()
    highlights = get_highlights()
    stats = get_stats_counts()

    return render_template(
        "home.html",
        projects=projects,
        project_thumbnails=project_thumbnails,
        certifications=certifications,
        skills=skills,
        experience=experience,
        profile=profile,
        about_content=about_content,
        about_intro=about_intro,
        about_interests=about_interests,
        highlights=highlights,
        stats=stats,
    )


@app.route("/about")
def about_page():
    profile = get_profile()
    about_content = get_about_content()
    about_intro = get_about_intro()
    about_interests = get_about_interests()
    highlights = get_highlights()
    stats = get_stats_counts()
    return render_template(
        "about.html",
        profile=profile,
        about_content=about_content,
        about_intro=about_intro,
        about_interests=about_interests,
        highlights=highlights,
        stats=stats,
    )


@app.route("/projects")
def projects_page():
    projects = get_projects()
    profile = get_profile()
    about_content = get_about_content()
    return render_template("projects.html", projects=projects, profile=profile, about_content=about_content)


def _api_file_url(value: str, endpoint: str) -> str:
    if not value:
        return ""
    if value.startswith("http"):
        return value
    return url_for(endpoint, filename=value)


@app.route("/api/projects", methods=["GET"])
def api_projects_list():
    projects = get_projects()
    for p in projects:
        p["cover_image_url"] = _api_file_url(p.get("cover_image", ""), "uploaded_project")
        p["image_urls"] = [_api_file_url(img, "uploaded_project") for img in (p.get("images") or [])]
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
@login_required
def api_projects_create():
    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    tech_stack = (payload.get("tech_stack") or "").strip()
    github_link = (payload.get("github_link") or "").strip()
    live_demo = (payload.get("live_demo") or "").strip()
    cover_image = (payload.get("cover_image") or "").strip() or None

    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400

    project = models.Project(
        title=title,
        description=description,
        tech_stack=tech_stack,
        github_link=github_link,
        project_image=cover_image,
        live_demo=live_demo,
    )
    db.session.add(project)
    db.session.flush()

    images = payload.get("images") or []
    if isinstance(images, list):
        for idx, img in enumerate(images[:6]):
            img_val = (img or "").strip()
            if img_val:
                db.session.add(models.ProjectImage(project_id=project.id, image_file=img_val, sort_order=idx))

    db.session.commit()
    return jsonify({"id": project.id}), 201


@app.route("/api/projects/<int:project_id>", methods=["PUT"])
@login_required
def api_projects_update(project_id: int):
    project = db.session.get(models.Project, project_id)
    if not project:
        return jsonify({"error": "not found"}), 404

    payload = request.get_json(silent=True) or {}
    for field, attr in [
        ("title", "title"),
        ("description", "description"),
        ("tech_stack", "tech_stack"),
        ("github_link", "github_link"),
        ("live_demo", "live_demo"),
        ("cover_image", "project_image"),
    ]:
        if field in payload:
            value = payload.get(field)
            setattr(project, attr, (value or "").strip() or None)

    if "images" in payload and isinstance(payload.get("images"), list):
        # Replace image list (max 6).
        project.images = []
        for idx, img in enumerate((payload.get("images") or [])[:6]):
            img_val = (img or "").strip()
            if img_val:
                project.images.append(models.ProjectImage(image_file=img_val, sort_order=idx))

    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/projects/<int:project_id>", methods=["DELETE"])
@login_required
def api_projects_delete(project_id: int):
    project = db.session.get(models.Project, project_id)
    if not project:
        return jsonify({"error": "not found"}), 404

    image_files = [img.image_file for img in (project.images or []) if img and img.image_file]
    cover = (project.project_image or "").strip()
    if cover and cover not in image_files:
        image_files.append(cover)

    db.session.delete(project)
    db.session.commit()

    for rel in image_files:
        _cloudinary_delete(rel)

    return jsonify({"ok": True})


@app.route("/skills")
def skills_page():
    skills = get_skills()
    profile = get_profile()
    about_content = get_about_content()
    return render_template("skills.html", skills=skills, profile=profile, about_content=about_content)


@app.route("/experience")
def experience_page():
    experience = get_experience()
    profile = get_profile()
    about_content = get_about_content()
    return render_template("experience.html", experience=experience, profile=profile, about_content=about_content)


@app.route("/certifications")
def certifications_page():
    certifications = get_certifications()
    profile = get_profile()
    about_content = get_about_content()
    return render_template("certifications.html", certifications=certifications, profile=profile, about_content=about_content)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if 'admin_logged_in' in session:
        return redirect(url_for('admin'))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['admin_logged_in'] = True
            flash("Logged in successfully!", "success")
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('admin'))
        else:
            flash("Invalid username or password.", "error")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop('admin_logged_in', None)
    flash("Logged out successfully!", "success")
    return redirect(url_for('home'))


@app.route("/admin")
@login_required
def admin():
    projects = get_projects()
    certifications = get_certifications()
    skills = get_skills()
    experience = get_experience()
    profile = get_profile()
    about_content = get_about_content()
    about_intro = get_about_intro()
    about_interests = get_about_interests()
    highlights = get_highlights()

    return render_template(
        "admin.html",
        projects=projects,
        certifications=certifications,
        skills=skills,
        experience=experience,
        profile=profile,
        about_content=about_content,
        about_intro=about_intro,
        about_interests=about_interests,
        highlights=highlights,
    )


@app.route("/contact", methods=["GET", "POST"])
def contact_page():
    profile = get_profile()
    next_dest = request.args.get("next", "").strip().lower()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or not message:
            flash("Please fill out all contact fields.", "error")
            if next_dest == "home":
                return redirect(url_for("home") + "#contact")
            return redirect(url_for("contact_page"))

        # Replace this with email sending or database storage as needed.
        flash("Thanks for your message! I'll get back to you soon.", "success")
        if next_dest == "home":
            return redirect(url_for("home") + "#contact")
        return redirect(url_for("contact_page"))

    return render_template("contact.html", profile=profile)


@app.route("/admin/certifications", methods=["GET", "POST"])
@login_required
def admin_certifications():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        platform = request.form.get("platform", "").strip()
        year = request.form.get("year", "").strip()
        file = request.files.get("certificate")

        if not title or not platform or not year or not file:
            flash("All fields are required.", "error")
            return redirect(url_for("admin_certifications"))

        if file and allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
            filename = secure_filename(file.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            filename = f"{timestamp}_{filename}"

            cloud_url = _cloudinary_upload(file, "portfolio/certificates", resource_type="raw")
            stored_value = cloud_url if cloud_url else filename
            if not cloud_url:
                file.save(os.path.join(UPLOAD_CERTIFICATES, filename))

            db.session.add(
                models.Certification(
                    title=title,
                    platform=platform,
                    year=year,
                    certificate_file=stored_value,
                )
            )
            db.session.commit()

            flash("Certification added successfully!", "success")
            return redirect(url_for("admin_certifications"))

        flash("Please upload a valid PDF file.", "error")
        return redirect(url_for("admin_certifications"))

    certifications = get_certifications()
    return render_template("admin_certifications.html", certifications=certifications)


@app.route("/add_certification", methods=["GET", "POST"])
@login_required
def add_certification():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        platform = request.form.get("platform", "").strip()
        year = request.form.get("year", "").strip()
        file = request.files.get("certificate")

        if not title or not platform or not year or not file:
            flash("All fields are required.", "error")
            return redirect(url_for("admin"))

        if file and allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
            filename = secure_filename(file.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            filename = f"{timestamp}_{filename}"

            cloud_url = _cloudinary_upload(file, "portfolio/certificates", resource_type="raw")
            stored_value = cloud_url if cloud_url else filename
            if not cloud_url:
                file.save(os.path.join(UPLOAD_CERTIFICATES, filename))

            db.session.add(
                models.Certification(
                    title=title,
                    platform=platform,
                    year=year,
                    certificate_file=stored_value,
                )
            )
            db.session.commit()

            flash("Certification added successfully!", "success")
            return redirect(url_for("admin"))

        flash("Please upload a valid PDF file.", "error")
        return redirect(url_for("admin"))

    certifications = get_certifications()
    return render_template("add_certification.html", certifications=certifications)


@app.route("/admin/projects", methods=["GET", "POST"])
@login_required
def admin_projects():
    if request.method == "GET":
        # This endpoint is used by the "Add Project" form on /admin.
        # If someone opens it directly, avoid a confusing 405 page.
        return redirect(url_for("admin"))

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    tech_stack = request.form.get("tech_stack", "").strip()
    github_link = request.form.get("github_link", "").strip()
    live_demo = request.form.get("live_demo", "").strip()
    files = request.files.getlist("project_images")

    if not title or not description:
        flash("Title and description are required.", "error")
        return redirect(url_for("admin"))

    # Validate and cap uploads (max 6 images per project).
    valid_files = []
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename, ALLOWED_EXTENSIONS_IMG):
            continue
        valid_files.append(f)

    if len(valid_files) > 6:
        flash("You can upload a maximum of 6 images per project.", "error")
        return redirect(url_for("admin"))

    # Insert project first to get an ID for folder structure.
    project = models.Project(
        title=title,
        description=description,
        tech_stack=tech_stack,
        github_link=github_link,
        project_image=None,
        live_demo=live_demo,
    )
    db.session.add(project)
    db.session.flush()
    project_id = project.id

    if valid_files:
        project_folder_name = f"project_{project_id}"
        project_folder = os.path.join(UPLOAD_PROJECTS_NEW, project_folder_name)
        os.makedirs(project_folder, exist_ok=True)

        saved = []
        for f in valid_files:
            filename = secure_filename(f.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            filename = f"{timestamp}_{filename}"

            cloud_url = _cloudinary_upload(f, f"portfolio/projects/{project_folder_name}")
            if cloud_url:
                saved.append(cloud_url)
            else:
                f.save(os.path.join(project_folder, filename))
                saved.append(f"{project_folder_name}/{filename}")

        cover = saved[0]
        project.project_image = cover

        for idx, rel_path in enumerate(saved):
            db.session.add(models.ProjectImage(project_id=project_id, image_file=rel_path, sort_order=idx))

    db.session.commit()

    flash("Project added successfully!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/projects/manage")
@login_required
def admin_projects_manage():
    projects = get_projects()
    return render_template("admin_projects.html", projects=projects)


@app.route("/admin/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = db.session.get(models.Project, project_id)
    if not project:
        flash("Project not found.", "error")
        return redirect(url_for("admin_projects_manage"))

    image_files = [img.image_file for img in (project.images or []) if img and img.image_file]
    cover = project.project_image or ""
    if cover and cover not in image_files:
        image_files.append(cover)

    db.session.delete(project)
    db.session.commit()

    # Delete from Cloudinary if URLs are stored
    for rel in image_files:
        _cloudinary_delete(rel)

    # Try to remove uploaded files/folders. Ignore failures (Windows locks etc).
    try:
        # New structure: uploads/projects/project_<id>/...
        project_folder = os.path.join(UPLOAD_PROJECTS_NEW, f"project_{project_id}")
        if os.path.isdir(project_folder):
            for root, _dirs, files in os.walk(project_folder, topdown=False):
                for f in files:
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass
            try:
                os.rmdir(project_folder)
            except OSError:
                pass

        # Also try to remove individual files (works for legacy flat storage too).
        for rel in image_files:
            for base in (UPLOAD_PROJECTS_NEW, UPLOAD_PROJECTS_LEGACY):
                abs_path = os.path.join(base, rel)
                if os.path.isfile(abs_path):
                    try:
                        os.remove(abs_path)
                    except OSError:
                        pass
    except OSError:
        pass

    flash("Project deleted.", "success")
    return redirect(url_for("admin_projects_manage"))


@app.route("/admin/project_thumbnails", methods=["POST"])
@login_required
def admin_project_thumbnails_add():
    title = request.form.get("title", "").strip()
    file = request.files.get("thumbnail_image")
    sort_order = request.form.get("sort_order", "0").strip()

    if not title:
        flash("Thumbnail title is required.", "error")
        return redirect(url_for("admin"))

    if not file or not file.filename or not allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG):
        flash("Please upload a valid thumbnail image.", "error")
        return redirect(url_for("admin"))

    try:
        sort_order_val = int(sort_order) if sort_order else 0
    except ValueError:
        sort_order_val = 0

    filename = secure_filename(file.filename)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{filename}"

    cloud_url = _cloudinary_upload(file, "portfolio/project_thumbnails")
    stored_value = cloud_url if cloud_url else filename
    if not cloud_url:
        file.save(os.path.join(UPLOAD_PROJECT_THUMBNAILS, filename))

    db.session.add(
        models.ProjectThumbnail(
            title=title,
            image_file=stored_value,
            sort_order=sort_order_val,
        )
    )
    db.session.commit()

    flash("Project thumbnail added.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/project_thumbnails/manage")
@login_required
def admin_project_thumbnails_manage():
    thumbs = get_project_thumbnails()
    return render_template("admin_project_thumbnails.html", thumbnails=thumbs)


@app.route("/admin/project_thumbnails/<int:thumb_id>/delete", methods=["POST"])
@login_required
def delete_project_thumbnail(thumb_id):
    thumb = db.session.get(models.ProjectThumbnail, thumb_id)
    img = (thumb.image_file if thumb else "") or ""
    if thumb:
        db.session.delete(thumb)
        db.session.commit()

    if img:
        _cloudinary_delete(img)
        try:
            p = os.path.join(UPLOAD_PROJECT_THUMBNAILS, img)
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

    flash("Thumbnail deleted.", "success")
    return redirect(url_for("admin_project_thumbnails_manage"))


@app.route("/admin/skills", methods=["GET", "POST"])
@login_required
def admin_skills():
    if request.method == "GET":
        # Send users to the dedicated manage page (includes delete UI).
        return redirect(url_for("admin_skills_manage"))

    skill_name = request.form.get("skill_name", "").strip()

    if not skill_name:
        flash("Skill name is required.", "error")
        return redirect(url_for("admin"))

    db.session.add(models.Skill(skill_name=skill_name))
    db.session.commit()

    flash("Skill added successfully!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/skills/manage")
@login_required
def admin_skills_manage():
    skills = get_skills()
    return render_template("admin_skills.html", skills=skills)


@app.route("/add_skill", methods=["GET", "POST"])
@login_required
def add_skill():
    if request.method == "POST":
        skill_name = request.form.get("skill_name", "").strip()

        if not skill_name:
            flash("Skill name is required.", "error")
            return redirect(url_for("admin"))

        db.session.add(models.Skill(skill_name=skill_name))
        db.session.commit()

        flash("Skill added successfully!", "success")
        return redirect(url_for("admin"))

    skills = get_skills()
    return render_template("add_skill.html", skills=skills)


@app.route("/admin/experience", methods=["GET", "POST"])
@login_required
def admin_experience():
    if request.method == "GET":
        # Send users to the dedicated manage page (includes delete UI).
        return redirect(url_for("admin_experience_manage"))

    role = request.form.get("role", "").strip()
    organization = request.form.get("organization", "").strip()
    duration = request.form.get("duration", "").strip()
    description = request.form.get("description", "").strip()
    file = request.files.get("experience_file")

    if not role or not organization or not duration or not description:
        flash("All fields are required.", "error")
        return redirect(url_for("admin"))

    experience_filename = ""
    if file and file.filename:
        if not allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
            flash("Invalid file type. Please upload a PDF.", "error")
            return redirect(url_for("admin"))

        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        base_filename = f"{timestamp}_{filename}"

        cloud_url = _cloudinary_upload(file, "portfolio/experience", resource_type="raw")
        if cloud_url:
            experience_filename = cloud_url
        else:
            file.save(os.path.join(UPLOAD_EXPERIENCE, base_filename))
            experience_filename = base_filename

    db.session.add(
        models.Experience(
            role=role,
            organization=organization,
            duration=duration,
            description=description,
            experience_file=experience_filename,
        )
    )
    db.session.commit()

    flash("Experience added successfully!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/experience/manage")
@login_required
def admin_experience_manage():
    experience = get_experience()
    return render_template("admin_experience.html", experience=experience)


@app.route("/add_experience", methods=["GET", "POST"])
@login_required
def add_experience():
    if request.method == "POST":
        role = request.form.get("role", "").strip()
        organization = request.form.get("organization", "").strip()
        duration = request.form.get("duration", "").strip()
        description = request.form.get("description", "").strip()
        file = request.files.get("experience_file")

        if not role or not organization or not duration or not description:
            flash("All fields are required.", "error")
            return redirect(url_for("admin"))

        experience_filename = ""
        if file and file.filename:
            if not allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
                flash("Invalid file type. Please upload a PDF.", "error")
                return redirect(url_for("admin"))

            filename = secure_filename(file.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            base_filename = f"{timestamp}_{filename}"

            cloud_url = _cloudinary_upload(file, "portfolio/experience", resource_type="raw")
            if cloud_url:
                experience_filename = cloud_url
            else:
                file.save(os.path.join(UPLOAD_EXPERIENCE, base_filename))
                experience_filename = base_filename

        db.session.add(
            models.Experience(
                role=role,
                organization=organization,
                duration=duration,
                description=description,
                experience_file=experience_filename,
            )
        )
        db.session.commit()

        flash("Experience added successfully!", "success")
        return redirect(url_for("admin"))

    experience = get_experience()
    return render_template("add_experience.html", experience=experience)


@app.route("/admin/profile", methods=["GET", "POST"])
@login_required
def admin_profile():
    if request.method == "GET":
        # Avoid a 405 if opened directly; the full editor is here.
        return redirect(url_for("update_profile"))

    name = request.form.get("name", "").strip()
    title = request.form.get("title", "").strip()
    about = request.form.get("about", "").strip()
    email = request.form.get("email", "").strip()
    github = request.form.get("github", "").strip()
    linkedin = request.form.get("linkedin", "").strip()

    if not name or not title or not about:
        flash("Name, title, and about are required.", "error")
        return redirect(url_for("admin"))

    profile = db.session.get(models.Profile, 1)
    if profile is None:
        profile = models.Profile(id=1)
        db.session.add(profile)

    profile.name = name
    profile.title = title
    profile.about = about
    profile.email = email
    profile.github = github
    profile.linkedin = linkedin
    db.session.commit()

    flash("Profile updated successfully!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/about", methods=["POST"])
@login_required
def admin_about():
    preview_text = request.form.get("preview_text", "").strip()
    details_text = request.form.get("details_text", "").strip()

    row = db.session.get(models.AboutContent, 1)
    if row is None:
        row = models.AboutContent(id=1, preview_text="", details_text="")
        db.session.add(row)
    row.preview_text = preview_text
    row.details_text = details_text
    db.session.commit()

    flash("About content updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/about_intro", methods=["POST"])
@login_required
def admin_about_intro():
    headline = request.form.get("headline", "").strip()
    role_line = request.form.get("role_line", "").strip()
    short_desc = request.form.get("short_desc", "").strip()

    row = db.session.get(models.AboutIntro, 1)
    if row is None:
        row = models.AboutIntro(id=1, headline="", role_line="", short_desc="", about_image="")
        db.session.add(row)
    row.headline = headline
    row.role_line = role_line
    row.short_desc = short_desc
    db.session.commit()

    flash("About intro updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/about_image", methods=["POST"])
@login_required
def admin_about_image():
    file = request.files.get("about_image")
    if not file or not file.filename:
        flash("Please choose an image to upload.", "error")
        return redirect(url_for("admin"))

    if not allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG):
        flash("Please upload a valid image file (png/jpg/jpeg/gif/svg).", "error")
        return redirect(url_for("admin"))

    filename = secure_filename(file.filename)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{filename}"

    cloud_url = _cloudinary_upload(file, "portfolio/about")
    stored_value = cloud_url if cloud_url else filename
    if not cloud_url:
        file.save(os.path.join(UPLOAD_ABOUT, filename))

    row = db.session.get(models.AboutIntro, 1)
    if row is None:
        row = models.AboutIntro(id=1, headline="", role_line="", short_desc="", about_image="")
        db.session.add(row)
    row.about_image = stored_value

    # Backfill: if an older project has a single cover image, ensure it exists in project_images too.
    for p in models.Project.query.filter(models.Project.project_image.isnot(None)).all():
        cover = (p.project_image or "").strip()
        if not cover:
            continue
        exists = any((img.image_file or "") == cover for img in (p.images or []))
        if not exists:
            db.session.add(models.ProjectImage(project_id=p.id, image_file=cover, sort_order=0))

    db.session.commit()

    flash("About section image updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/interests", methods=["POST"])
@login_required
def admin_interests_add():
    label = request.form.get("label", "").strip()
    count_value = request.form.get("count_value", "0").strip()
    sort_order = request.form.get("sort_order", "0").strip()

    if not label:
        flash("Interest label is required.", "error")
        return redirect(url_for("admin"))

    try:
        count_value_int = int(count_value) if count_value else 0
    except ValueError:
        count_value_int = 0

    try:
        sort_order_int = int(sort_order) if sort_order else 0
    except ValueError:
        sort_order_int = 0

    db.session.add(
        models.AboutInterest(label=label, count_value=count_value_int, sort_order=sort_order_int)
    )
    db.session.commit()

    flash("Interest added.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/interests/<int:interest_id>/delete", methods=["POST"])
@login_required
def delete_interest(interest_id):
    row = db.session.get(models.AboutInterest, interest_id)
    if row:
        db.session.delete(row)
        db.session.commit()

    flash("Interest deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/highlights", methods=["POST"])
@login_required
def admin_highlights():
    icon_key = request.form.get("icon_key", "").strip()
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    sort_order = request.form.get("sort_order", "0").strip()

    if not title or not description:
        flash("Highlight title and description are required.", "error")
        return redirect(url_for("admin"))

    try:
        sort_order_int = int(sort_order) if sort_order else 0
    except ValueError:
        sort_order_int = 0

    db.session.add(
        models.Highlight(
            icon_key=icon_key,
            title=title,
            description=description,
            sort_order=sort_order_int,
        )
    )
    db.session.commit()

    flash("Highlight added.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/highlights/<int:highlight_id>/delete", methods=["POST"])
@login_required
def delete_highlight(highlight_id):
    row = db.session.get(models.Highlight, highlight_id)
    if row:
        db.session.delete(row)
        db.session.commit()

    flash("Highlight deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/skills/<int:skill_id>/delete", methods=["POST"])
@login_required
def delete_skill(skill_id):
    row = db.session.get(models.Skill, skill_id)
    if row:
        db.session.delete(row)
        db.session.commit()

    flash("Skill deleted.", "success")
    return redirect(url_for("admin_skills_manage"))


@app.route("/admin/experience/<int:experience_id>/delete", methods=["POST"])
@login_required
def delete_experience(experience_id):
    row = db.session.get(models.Experience, experience_id)
    experience_file = row.experience_file if row else None
    if row:
        db.session.delete(row)
        db.session.commit()

    if experience_file:
        _cloudinary_delete(experience_file)
        file_path = os.path.join(UPLOAD_EXPERIENCE, experience_file)
        if os.path.exists(file_path):
            os.remove(file_path)

    flash("Experience deleted.", "success")
    return redirect(url_for("admin_experience_manage"))


@app.route("/admin/certifications/<int:cert_id>/delete", methods=["POST"])
@login_required
def delete_certification(cert_id):
    row = db.session.get(models.Certification, cert_id)
    certificate_file = row.certificate_file if row else None
    if row:
        db.session.delete(row)
        db.session.commit()

    if certificate_file:
        _cloudinary_delete(certificate_file)
        file_path = os.path.join(UPLOAD_CERTIFICATES, certificate_file)
        if os.path.exists(file_path):
            os.remove(file_path)

    flash("Certification deleted.", "success")
    return redirect(url_for("admin_certifications"))


@app.route("/update_profile")
@login_required
def update_profile():
    profile = get_profile()
    return render_template("update_profile.html", profile=profile)


@app.route("/upload_resume", methods=["GET", "POST"])
@login_required
def upload_resume():
    if request.method == "POST":
        if "resume" not in request.files:
            flash("No file selected.", "error")
            return redirect(url_for("admin"))

        file = request.files["resume"]
        if file.filename == "":
            flash("No file selected.", "error")
            return redirect(url_for("admin"))

        if not allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
            flash("Invalid file type. Only PDF files are allowed.", "error")
            return redirect(url_for("admin"))

        filename = secure_filename(f"resume_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")

        cloud_url = _cloudinary_upload(file, "portfolio/resume", resource_type="raw")
        if cloud_url:
            stored_value = cloud_url
        else:
            file_path = os.path.join(UPLOAD_RESUME, filename)
            file.save(file_path)
            stored_value = filename

        profile = db.session.get(models.Profile, 1)
        if profile is None:
            profile = models.Profile(id=1)
            db.session.add(profile)
        profile.resume_file = stored_value
        db.session.commit()

        flash("Resume uploaded successfully!", "success")
        return redirect(url_for("admin"))

    return render_template("upload_resume.html")


@app.route("/upload_profile_image", methods=["GET", "POST"])
@login_required
def upload_profile_image():
    if request.method == "POST":
        if "profile_image" not in request.files:
            flash("No file selected.", "error")
            return redirect(url_for("admin"))

        file = request.files["profile_image"]
        if file.filename == "":
            flash("No file selected.", "error")
            return redirect(url_for("admin"))

        if not allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG):
            flash("Invalid file type. Only image files are allowed.", "error")
            return redirect(url_for("admin"))

        # Remove old profile image if exists
        profile = db.session.get(models.Profile, 1)
        old_image = (profile.profile_image if profile else "") or ""
        if old_image:
            _cloudinary_delete(old_image)
            old_path = os.path.join(UPLOAD_PROFILE, old_image)
            if os.path.exists(old_path):
                os.remove(old_path)

        filename = secure_filename(f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")

        cloud_url = _cloudinary_upload(file, "portfolio/profile")
        if cloud_url:
            stored_value = cloud_url
        else:
            file_path = os.path.join(UPLOAD_PROFILE, filename)
            file.save(file_path)
            stored_value = filename

        if profile is None:
            profile = models.Profile(id=1)
            db.session.add(profile)
        profile.profile_image = stored_value
        db.session.commit()

        flash("Profile image uploaded successfully!", "success")
        return redirect(url_for("admin"))

    return render_template("upload_profile_image.html")





@app.route("/uploads/certificates/<path:filename>")
def uploaded_certificate(filename):
    if _is_url(filename):
        return redirect(filename)
    return send_from_directory(UPLOAD_CERTIFICATES, filename)


@app.route("/uploads/projects/<path:filename>")
def uploaded_project(filename):
    if _is_url(filename):
        return redirect(filename)
    new_path = os.path.join(UPLOAD_PROJECTS_NEW, filename)
    if os.path.exists(new_path):
        return send_from_directory(UPLOAD_PROJECTS_NEW, filename)

    legacy_path = os.path.join(UPLOAD_PROJECTS_LEGACY, filename)
    if os.path.exists(legacy_path):
        return send_from_directory(UPLOAD_PROJECTS_LEGACY, filename)

    # Default: try new folder (will 404 with a proper message).
    return send_from_directory(UPLOAD_PROJECTS_NEW, filename)


# Backward-compatible URL (legacy path used in older templates).
@app.route("/uploads/project_images/<path:filename>")
def uploaded_project_legacy(filename):
    return uploaded_project(filename)


@app.route("/uploads/profile/<path:filename>")
def uploaded_profile(filename):
    if _is_url(filename):
        return redirect(filename)
    return send_from_directory(UPLOAD_PROFILE, filename)


@app.route("/uploads/about/<path:filename>")
def uploaded_about(filename):
    if _is_url(filename):
        return redirect(filename)
    return send_from_directory(UPLOAD_ABOUT, filename)


@app.route("/uploads/project_thumbnails/<path:filename>")
def uploaded_project_thumbnail(filename):
    if _is_url(filename):
        return redirect(filename)
    return send_from_directory(UPLOAD_PROJECT_THUMBNAILS, filename)


@app.route("/uploads/resume/<path:filename>")
def uploaded_resume(filename):
    if _is_url(filename):
        return redirect(filename)
    return send_from_directory(UPLOAD_RESUME, filename)


@app.route("/uploads/experience/<path:filename>")
def uploaded_experience(filename):
    if _is_url(filename):
        return redirect(filename)
    return send_from_directory(UPLOAD_EXPERIENCE, filename)


if __name__ == "__main__":
    # Enable the reloader in development so templates/routes stay in sync.
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True)
