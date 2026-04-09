import os
import sqlite3
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret")

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
# Prefer a clean, writable DB file. Keep it out of /static and /uploads.
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PRIMARY_PATH = os.path.join(DATA_DIR, os.environ.get("PORTFOLIO_DB", "portfolio.db"))
# If the primary DB is left with a locked hot-journal (common on Windows when a process crashes or holds the file),
# SQLite can start throwing "disk I/O error" on open. Keep a fallback copy that we can switch to automatically.
DB_FALLBACK_PATH = os.path.join(DATA_DIR, "portfolio_live.db")
UPLOAD_CERTIFICATES = os.path.join(BASE_DIR, "uploads", "certificates")
UPLOAD_PROJECTS_NEW = os.path.join(BASE_DIR, "uploads", "projects")
# Legacy flat folder used by older versions of the app.
UPLOAD_PROJECTS_LEGACY = os.path.join(BASE_DIR, "uploads", "project_images")
UPLOAD_PROJECT_THUMBNAILS = os.path.join(BASE_DIR, "uploads", "project_thumbnails")
UPLOAD_PROFILE = os.path.join(BASE_DIR, "uploads", "profile")
UPLOAD_ABOUT = os.path.join(BASE_DIR, "uploads", "about")
UPLOAD_RESUME = os.path.join(BASE_DIR, "uploads", "resume")
UPLOAD_EXPERIENCE = os.path.join(BASE_DIR, "uploads", "experience")

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

    conn.commit()
    conn.close()

try:
    init_db()
except sqlite3.OperationalError as exc:
    # If the DB is temporarily unavailable (e.g., locked by another process),
    # don't crash on import. Requests may still fail until the DB is writable.
    print(f"[WARN] init_db() failed: {exc}")


# GET PROJECTS
def get_projects():
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT id, title, description, tech_stack, github_link, project_image, live_demo FROM projects ORDER BY id DESC")
    rows = cursor.fetchall()

    cursor.execute("SELECT project_id, image_file FROM project_images ORDER BY sort_order ASC, id ASC")
    img_rows = cursor.fetchall()

    images_by_project = {}
    for pid, image_file in img_rows:
        images_by_project.setdefault(pid, []).append(image_file)

    projects = []
    for (pid, title, description, tech_stack, github_link, project_image, live_demo) in rows:
        images = images_by_project.get(pid, [])
        cover_image = project_image or (images[0] if images else "")
        projects.append(
            {
                "id": pid,
                "title": title or "",
                "description": description or "",
                "tech_stack": tech_stack or "",
                "github_link": github_link or "",
                "live_demo": live_demo or "",
                "cover_image": cover_image or "",
                "images": images,
            }
        )

    conn.close()

    return projects


# GET CERTIFICATIONS
def get_certifications():
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM certifications ORDER BY year DESC, id DESC")

    certs = cursor.fetchall()

    conn.close()

    return certs


# GET SKILLS
def get_skills():
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM skills")

    skills = cursor.fetchall()

    conn.close()

    return skills


# GET EXPERIENCE
def get_experience():
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM experience")

    experience = cursor.fetchall()

    conn.close()

    return experience


# GET PROFILE
def get_profile():
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM profile LIMIT 1")

    profile = cursor.fetchone()

    conn.close()

    return profile


def get_about_content():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT preview_text, details_text FROM about_content WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    preview_text = row[0] if row and row[0] else ""
    details_text = row[1] if row and row[1] else ""
    return {"preview_text": preview_text, "details_text": details_text}


def get_about_intro():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT headline, role_line, short_desc, about_image FROM about_intro WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    return {
        "headline": row[0] if row and row[0] else "",
        "role_line": row[1] if row and row[1] else "",
        "short_desc": row[2] if row and row[2] else "",
        "about_image": row[3] if row and row[3] else "",
    }


def get_about_interests():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, label, count_value FROM about_interests ORDER BY sort_order ASC, id ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_highlights():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, icon_key, title, description FROM highlights ORDER BY sort_order ASC, id ASC")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_stats_counts():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM projects")
    projects_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM skills")
    skills_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM certifications")
    certifications_count = cursor.fetchone()[0]
    conn.close()

    return {
        "projects": projects_count,
        "skills": skills_count,
        "certifications": certifications_count,
    }


def get_project_thumbnails():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, image_file FROM project_thumbnails ORDER BY sort_order ASC, id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1] or "", "image_file": r[2] or ""} for r in rows]


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
            file.save(os.path.join(UPLOAD_CERTIFICATES, filename))

            conn = db_connect()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO certifications (title, platform, year, certificate_file) VALUES (?, ?, ?, ?)",
                (title, platform, year, filename),
            )
            conn.commit()
            conn.close()

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
            file.save(os.path.join(UPLOAD_CERTIFICATES, filename))

            conn = db_connect()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO certifications (title, platform, year, certificate_file) VALUES (?, ?, ?, ?)",
                (title, platform, year, filename),
            )
            conn.commit()
            conn.close()

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

    conn = db_connect()
    cursor = conn.cursor()

    # Validate and cap uploads (max 6 images per project).
    valid_files = []
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename, ALLOWED_EXTENSIONS_IMG):
            continue
        valid_files.append(f)

    if len(valid_files) > 6:
        conn.close()
        flash("You can upload a maximum of 6 images per project.", "error")
        return redirect(url_for("admin"))

    # Insert project first to get an ID for folder structure.
    cursor.execute(
        "INSERT INTO projects (title, description, tech_stack, github_link, project_image, live_demo) VALUES (?, ?, ?, ?, ?, ?)",
        (title, description, tech_stack, github_link, None, live_demo),
    )
    project_id = cursor.lastrowid

    if valid_files:
        project_folder_name = f"project_{project_id}"
        project_folder = os.path.join(UPLOAD_PROJECTS_NEW, project_folder_name)
        os.makedirs(project_folder, exist_ok=True)

        saved = []
        for f in valid_files:
            filename = secure_filename(f.filename)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            filename = f"{timestamp}_{filename}"
            f.save(os.path.join(project_folder, filename))
            saved.append(f"{project_folder_name}/{filename}")

        cover = saved[0]
        cursor.execute("UPDATE projects SET project_image = ? WHERE id = ?", (cover, project_id))

        for idx, rel_path in enumerate(saved):
            cursor.execute(
                "INSERT INTO project_images (project_id, image_file, sort_order) VALUES (?, ?, ?)",
                (project_id, rel_path, idx),
            )
    conn.commit()
    conn.close()

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
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT image_file FROM project_images WHERE project_id = ?", (project_id,))
    image_rows = cursor.fetchall()
    image_files = [r[0] for r in image_rows if r and r[0]]

    cursor.execute("SELECT project_image FROM projects WHERE id = ?", (project_id,))
    row = cursor.fetchone()
    cover = row[0] if row and row[0] else ""
    if cover and cover not in image_files:
        image_files.append(cover)

    cursor.execute("DELETE FROM project_images WHERE project_id = ?", (project_id,))
    cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()

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
    file.save(os.path.join(UPLOAD_PROJECT_THUMBNAILS, filename))

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO project_thumbnails (title, image_file, sort_order) VALUES (?, ?, ?)",
        (title, filename, sort_order_val),
    )
    conn.commit()
    conn.close()

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
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("SELECT image_file FROM project_thumbnails WHERE id = ?", (thumb_id,))
    row = cursor.fetchone()
    img = row[0] if row and row[0] else ""
    cursor.execute("DELETE FROM project_thumbnails WHERE id = ?", (thumb_id,))
    conn.commit()
    conn.close()

    if img:
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

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO skills (skill_name) VALUES (?)", (skill_name,))
    conn.commit()
    conn.close()

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

        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO skills (skill_name) VALUES (?)", (skill_name,))
        conn.commit()
        conn.close()

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
        experience_filename = f"{timestamp}_{filename}"
        file.save(os.path.join(UPLOAD_EXPERIENCE, experience_filename))

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO experience (role, organization, duration, description, experience_file) VALUES (?, ?, ?, ?, ?)",
        (role, organization, duration, description, experience_filename),
    )
    conn.commit()
    conn.close()

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
            experience_filename = f"{timestamp}_{filename}"
            file.save(os.path.join(UPLOAD_EXPERIENCE, experience_filename))

        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO experience (role, organization, duration, description, experience_file) VALUES (?, ?, ?, ?, ?)",
            (role, organization, duration, description, experience_filename),
        )
        conn.commit()
        conn.close()

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

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO profile (id, name, title, about, email, github, linkedin, resume_file, profile_image) VALUES (1, ?, ?, ?, ?, ?, ?, (SELECT resume_file FROM profile WHERE id=1), (SELECT profile_image FROM profile WHERE id=1))",
        (name, title, about, email, github, linkedin),
    )
    conn.commit()
    conn.close()

    flash("Profile updated successfully!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/about", methods=["POST"])
@login_required
def admin_about():
    preview_text = request.form.get("preview_text", "").strip()
    details_text = request.form.get("details_text", "").strip()

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE about_content SET preview_text = ?, details_text = ? WHERE id = 1",
        (preview_text, details_text),
    )
    conn.commit()
    conn.close()

    flash("About content updated.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/about_intro", methods=["POST"])
@login_required
def admin_about_intro():
    headline = request.form.get("headline", "").strip()
    role_line = request.form.get("role_line", "").strip()
    short_desc = request.form.get("short_desc", "").strip()

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE about_intro SET headline = ?, role_line = ?, short_desc = ? WHERE id = 1",
        (headline, role_line, short_desc),
    )
    conn.commit()
    conn.close()

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
    file.save(os.path.join(UPLOAD_ABOUT, filename))

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("UPDATE about_intro SET about_image = ? WHERE id = 1", (filename,))
    conn.commit()

    # Backfill: if an older project has a single cover image, ensure it exists in project_images too.
    try:
        cursor.execute("SELECT id, project_image FROM projects WHERE project_image IS NOT NULL AND project_image != ''")
        rows = cursor.fetchall()
        for pid, cover in rows:
            cursor.execute(
                "SELECT 1 FROM project_images WHERE project_id = ? AND image_file = ?",
                (pid, cover),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    "INSERT INTO project_images (project_id, image_file, sort_order) VALUES (?, ?, 0)",
                    (pid, cover),
                )
        conn.commit()
    except sqlite3.OperationalError:
        # If the DB is in a transitional state, don't block startup.
        pass

    conn.close()

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

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO about_interests (label, count_value, sort_order) VALUES (?, ?, ?)",
        (label, count_value_int, sort_order_int),
    )
    conn.commit()
    conn.close()

    flash("Interest added.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/interests/<int:interest_id>/delete", methods=["POST"])
@login_required
def delete_interest(interest_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM about_interests WHERE id = ?", (interest_id,))
    conn.commit()
    conn.close()

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

    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO highlights (icon_key, title, description, sort_order) VALUES (?, ?, ?, ?)",
        (icon_key, title, description, sort_order_int),
    )
    conn.commit()
    conn.close()

    flash("Highlight added.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/highlights/<int:highlight_id>/delete", methods=["POST"])
@login_required
def delete_highlight(highlight_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
    conn.commit()
    conn.close()

    flash("Highlight deleted.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/skills/<int:skill_id>/delete", methods=["POST"])
@login_required
def delete_skill(skill_id):
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    conn.commit()
    conn.close()

    flash("Skill deleted.", "success")
    return redirect(url_for("admin_skills_manage"))


@app.route("/admin/experience/<int:experience_id>/delete", methods=["POST"])
@login_required
def delete_experience(experience_id):
    conn = db_connect()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT experience_file FROM experience WHERE id = ?", (experience_id,))
        row = cursor.fetchone()
        experience_file = row[0] if row else None
    except sqlite3.OperationalError:
        # Backward compatibility if the column doesn't exist for some reason.
        experience_file = None

    cursor.execute("DELETE FROM experience WHERE id = ?", (experience_id,))
    conn.commit()
    conn.close()

    if experience_file:
        file_path = os.path.join(UPLOAD_EXPERIENCE, experience_file)
        if os.path.exists(file_path):
            os.remove(file_path)

    flash("Experience deleted.", "success")
    return redirect(url_for("admin_experience_manage"))


@app.route("/admin/certifications/<int:cert_id>/delete", methods=["POST"])
@login_required
def delete_certification(cert_id):
    conn = db_connect()
    cursor = conn.cursor()

    cursor.execute("SELECT certificate_file FROM certifications WHERE id = ?", (cert_id,))
    row = cursor.fetchone()
    certificate_file = row[0] if row else None

    cursor.execute("DELETE FROM certifications WHERE id = ?", (cert_id,))
    conn.commit()
    conn.close()

    if certificate_file:
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
        file_path = os.path.join(UPLOAD_RESUME, filename)
        file.save(file_path)

        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("UPDATE profile SET resume_file = ? WHERE id = 1", (filename,))
        conn.commit()
        conn.close()

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
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute("SELECT profile_image FROM profile WHERE id = 1")
        old_image = cursor.fetchone()
        if old_image and old_image[0]:
            old_path = os.path.join(UPLOAD_PROFILE, old_image[0])
            if os.path.exists(old_path):
                os.remove(old_path)

        filename = secure_filename(f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
        file_path = os.path.join(UPLOAD_PROFILE, filename)
        file.save(file_path)

        cursor.execute("UPDATE profile SET profile_image = ? WHERE id = 1", (filename,))
        conn.commit()
        conn.close()

        flash("Profile image uploaded successfully!", "success")
        return redirect(url_for("admin"))

    return render_template("upload_profile_image.html")





@app.route("/uploads/certificates/<path:filename>")
def uploaded_certificate(filename):
    return send_from_directory(UPLOAD_CERTIFICATES, filename)


@app.route("/uploads/projects/<path:filename>")
def uploaded_project(filename):
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
    return send_from_directory(UPLOAD_PROFILE, filename)


@app.route("/uploads/about/<path:filename>")
def uploaded_about(filename):
    return send_from_directory(UPLOAD_ABOUT, filename)


@app.route("/uploads/project_thumbnails/<path:filename>")
def uploaded_project_thumbnail(filename):
    return send_from_directory(UPLOAD_PROJECT_THUMBNAILS, filename)


@app.route("/uploads/resume/<path:filename>")
def uploaded_resume(filename):
    return send_from_directory(UPLOAD_RESUME, filename)


@app.route("/uploads/experience/<path:filename>")
def uploaded_experience(filename):
    return send_from_directory(UPLOAD_EXPERIENCE, filename)


if __name__ == "__main__":
    # Enable the reloader in development so templates/routes stay in sync.
    app.run(debug=True, use_reloader=True)
