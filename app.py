import os
import functools

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from db_config import get_database_uri
from extensions import db, migrate

# ---------------------------------------------------------------------------
# Cloudinary – required storage backend.
# Configure ONLY via CLOUDINARY_URL (cloudinary://api_key:api_secret@cloud_name).
# No local filesystem fallback is allowed in production.
# ---------------------------------------------------------------------------
try:
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(secure=True)

    _CLOUDINARY_ENABLED = bool(
        (os.environ.get("CLOUDINARY_URL", "").strip())
        and cloudinary.config().cloud_name
        and cloudinary.config().api_key
        and cloudinary.config().api_secret
    )
except ImportError:
    cloudinary = None  # type: ignore[assignment]
    _CLOUDINARY_ENABLED = False


def _require_cloudinary() -> None:
    if not _CLOUDINARY_ENABLED:
        raise RuntimeError(
            "CLOUDINARY_URL is required for uploads. This app no longer supports local file storage."
        )

def _cloudinary_upload(file_obj, folder: str, resource_type: str = "auto") -> str:
    _require_cloudinary()

    # Read bytes from Werkzeug FileStorage or any file-like object
    if hasattr(file_obj, 'read'):
        file_data = file_obj.read()
        filename = getattr(file_obj, 'filename', None)
    else:
        file_data = file_obj
        filename = None

    upload_kwargs = dict(
        folder=folder,
        resource_type=resource_type,
        use_filename=True,
        unique_filename=True,
        overwrite=False,
    )

    # Explicitly preserve the original filename so Cloudinary keeps the extension
    if filename:
        upload_kwargs["public_id"] = os.path.splitext(filename)[0]
        # For raw uploads (PDFs), explicitly set the format
        if resource_type == "raw":
            ext = os.path.splitext(filename)[1].lstrip(".")
            if ext:
                upload_kwargs["format"] = ext  # e.g. "pdf"

    result = cloudinary.uploader.upload(file_data, **upload_kwargs)

    url = (result or {}).get("secure_url")
    if not url:
        raise RuntimeError("Cloudinary upload failed: no secure_url")
    return url


def _cloudinary_delete(url_or_public_id: str) -> None:
    if not _CLOUDINARY_ENABLED or not url_or_public_id:
        return

    try:
        public_id = url_or_public_id

        if url_or_public_id.startswith("http"):
            import re
            match = re.search(r"/upload/(?:v\d+/)?(.+?)(?:\.[a-zA-Z0-9]+)?$", url_or_public_id)
            if not match:
                return
            public_id = match.group(1)

        cloudinary.uploader.destroy(public_id)

    except Exception as exc:
        print(f"[WARN] Cloudinary delete failed: {exc}")


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="/static")

# FIX 1: SECRET_KEY must ALWAYS come from environment in production.
# Hardcoding a fallback is dangerous — use a strong random key in your
# Render environment variables. This will raise clearly if missing in prod.
_secret = os.environ.get("SECRET_KEY") or os.environ.get("FLASK_SECRET")
if not _secret:
    import warnings
    warnings.warn(
        "SECRET_KEY is not set — using an insecure dev default. "
        "Set SECRET_KEY in your Render environment variables.",
        stacklevel=1,
    )
    _secret = "dev-secret-change-me-in-production"
app.secret_key = _secret

_trust_proxy = os.environ.get("TRUST_PROXY_HEADERS", "").strip().lower() in {"1", "true", "yes"}
if _trust_proxy or os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

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


# ---------------------------------------------------------------------------
# FIX 2: Admin credentials — read from environment variables so you can
# change them on Render without redeploying. Never hardcode passwords.
# ---------------------------------------------------------------------------
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
_admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_PASSWORD_HASH = generate_password_hash(_admin_pw)


# FIX 3: login_required must use functools.wraps to preserve the original
# function name. Without this, Flask raises an AssertionError:
# "View function mapping is overwriting an existing endpoint function"
# when multiple routes use the decorator.
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_logged_in" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function


BASE_DIR = os.path.abspath(os.path.dirname(__file__))

ALLOWED_EXTENSIONS_PDF = {"pdf"}
ALLOWED_EXTENSIONS_IMG = {"png", "jpg", "jpeg", "gif", "svg"}


# ---------------------------------------------------------------------------
# Database (PostgreSQL via DATABASE_URL only)
# ---------------------------------------------------------------------------
database_url = get_database_uri()

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# FIX 4: On Render's free-tier Postgres the SSL cert is self-signed.
# "require" mode validates the server but not the CA — correct for Render.
# Also add pool_recycle so stale connections are refreshed (Render idles
# connections after ~5 min, causing "SSL connection has been closed" errors).
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,          # recycle before Render's ~300 s idle timeout
    "connect_args": {"sslmode": "require"},
}

db.init_app(app)
migrate.init_app(app, db)

import models  # noqa: E402

# FIX 5: AUTO_DB_CREATE default logic was inverted in the original code.
# Original: if env var is NOT set, it defaults to True (always runs).
# That is fine for first deploy, but it means every restart recreates tables.
# Kept the same behaviour but made the logic explicit and readable.
_AUTO_DB_CREATE = os.environ.get("AUTO_DB_CREATE", "true").strip().lower() in {"1", "true", "yes"}

if _AUTO_DB_CREATE:
    with app.app_context():
        db.create_all()
        from models import AboutContent, AboutIntro  # noqa: E402
        if db.session.get(AboutContent, 1) is None:
            db.session.add(AboutContent(id=1, preview_text="", details_text=""))
        if db.session.get(AboutIntro, 1) is None:
            db.session.add(AboutIntro(id=1, headline="", role_line="", short_desc="", about_image=""))
        db.session.commit()


def allowed_file(filename, allowed_ext):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_ext


# FIX 6: inject_static_version — on Render the static folder is read-only
# and os.path.getmtime may fail. Fall back gracefully so the app doesn't
# crash on startup just because a CSS file's mtime can't be read.
@app.context_processor
def inject_static_version():
    try:
        css_path = os.path.join(app.static_folder, "css", "style.css")
        anim_path = os.path.join(app.static_folder, "css", "animations.css")
        js_path = os.path.join(app.static_folder, "js", "main.js")
        mtimes = []
        for p in [css_path, js_path, anim_path]:
            if os.path.exists(p):
                mtimes.append(os.path.getmtime(p))
        v = int(max(mtimes)) if mtimes else 1
    except OSError:
        v = 1
    return {"static_v": v}


@app.context_processor
def inject_asset_url():
    def asset_url(value: str) -> str:
        if not value:
            return ""
        if value.startswith("http"):
            return value
        # FIX 7: If a legacy relative path somehow ended up in the DB
        # (from before the Cloudinary migration), return empty string
        # instead of silently serving a broken /static/... path.
        return ""
    return {"asset_url": asset_url}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

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


def get_certifications():
    rows = models.Certification.query.order_by(
        models.Certification.year.desc(), models.Certification.id.desc()
    ).all()
    return [(c.id, c.title, c.platform, c.year, c.certificate_file) for c in rows]


def get_skills():
    rows = models.Skill.query.order_by(models.Skill.id.asc()).all()
    return [(s.id, s.skill_name) for s in rows]


def get_experience():
    rows = models.Experience.query.order_by(models.Experience.id.asc()).all()
    return [(e.id, e.role, e.organization, e.duration, e.description, e.experience_file) for e in rows]


def get_profile():
    row = models.Profile.query.order_by(models.Profile.id.asc()).first()
    if not row:
        return None
    return (
        row.id, row.name, row.title, row.about,
        row.email, row.github, row.linkedin,
        row.resume_file, row.profile_image,
    )


def get_about_content():
    row = db.session.get(models.AboutContent, 1)
    return {
        "preview_text": row.preview_text if row and row.preview_text else "",
        "details_text": row.details_text if row and row.details_text else "",
    }


def get_about_intro():
    row = db.session.get(models.AboutIntro, 1)
    return {
        "headline":    row.headline    if row and row.headline    else "",
        "role_line":   row.role_line   if row and row.role_line   else "",
        "short_desc":  row.short_desc  if row and row.short_desc  else "",
        "about_image": row.about_image if row and row.about_image else "",
    }


def get_about_interests():
    rows = models.AboutInterest.query.order_by(
        models.AboutInterest.sort_order.asc(), models.AboutInterest.id.asc()
    ).all()
    return [(r.id, r.label, r.count_value) for r in rows]


def get_highlights():
    rows = models.Highlight.query.order_by(
        models.Highlight.sort_order.asc(), models.Highlight.id.asc()
    ).all()
    return [(r.id, r.icon_key, r.title, r.description) for r in rows]


def get_stats_counts():
    return {
        "projects":       models.Project.query.count(),
        "skills":         models.Skill.query.count(),
        "certifications": models.Certification.query.count(),
    }


def get_project_thumbnails():
    rows = models.ProjectThumbnail.query.order_by(
        models.ProjectThumbnail.sort_order.asc(), models.ProjectThumbnail.id.asc()
    ).all()
    return [{"id": r.id, "title": r.title or "", "image_file": r.image_file or ""} for r in rows]


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template(
        "home.html",
        projects=get_projects(),
        project_thumbnails=get_project_thumbnails(),
        certifications=get_certifications(),
        skills=get_skills(),
        experience=get_experience(),
        profile=get_profile(),
        about_content=get_about_content(),
        about_intro=get_about_intro(),
        about_interests=get_about_interests(),
        highlights=get_highlights(),
        stats=get_stats_counts(),
    )


@app.route("/about")
def about_page():
    return render_template(
        "about.html",
        profile=get_profile(),
        about_content=get_about_content(),
        about_intro=get_about_intro(),
        about_interests=get_about_interests(),
        highlights=get_highlights(),
        stats=get_stats_counts(),
    )


@app.route("/projects")
def projects_page():
    return render_template(
        "projects.html",
        projects=get_projects(),
        profile=get_profile(),
        about_content=get_about_content(),
    )


@app.route("/skills")
def skills_page():
    return render_template(
        "skills.html",
        skills=get_skills(),
        profile=get_profile(),
        about_content=get_about_content(),
    )


@app.route("/experience")
def experience_page():
    return render_template(
        "experience.html",
        experience=get_experience(),
        profile=get_profile(),
        about_content=get_about_content(),
    )


@app.route("/certifications")
def certifications_page():
    return render_template(
        "certifications.html",
        certifications=get_certifications(),
        profile=get_profile(),
        about_content=get_about_content(),
    )


@app.route("/contact", methods=["GET", "POST"])
def contact_page():
    profile = get_profile()
    next_dest = request.args.get("next", "").strip().lower()

    if request.method == "POST":
        name    = request.form.get("name", "").strip()
        email   = request.form.get("email", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or not message:
            flash("Please fill out all contact fields.", "error")
            if next_dest == "home":
                return redirect(url_for("home") + "#contact")
            return redirect(url_for("contact_page"))

        flash("Thanks for your message! I'll get back to you soon.", "success")
        if next_dest == "home":
            return redirect(url_for("home") + "#contact")
        return redirect(url_for("contact_page"))

    return render_template("contact.html", profile=profile)


# ---------------------------------------------------------------------------
# Projects API
# ---------------------------------------------------------------------------

def _api_file_url(value: str) -> str:
    if not value:
        return ""
    if value.startswith("http"):
        return value
    return ""


@app.route("/api/projects", methods=["GET"])
def api_projects_list():
    projects = get_projects()
    for p in projects:
        p["cover_image_url"] = _api_file_url(p.get("cover_image", ""))
        p["image_urls"] = [_api_file_url(img) for img in (p.get("images") or [])]
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
@login_required
def api_projects_create():
    payload = request.get_json(silent=True) or {}
    title       = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    tech_stack  = (payload.get("tech_stack") or "").strip()
    github_link = (payload.get("github_link") or "").strip()
    live_demo   = (payload.get("live_demo") or "").strip()
    cover_image = (payload.get("cover_image") or "").strip() or None

    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400
    if cover_image and not cover_image.startswith("http"):
        return jsonify({"error": "cover_image must be a Cloud URL"}), 400

    project = models.Project(
        title=title, description=description, tech_stack=tech_stack,
        github_link=github_link, project_image=cover_image, live_demo=live_demo,
    )
    db.session.add(project)
    db.session.flush()

    images = payload.get("images") or []
    if isinstance(images, list):
        for idx, img in enumerate(images[:6]):
            img_val = (img or "").strip()
            if img_val and not img_val.startswith("http"):
                return jsonify({"error": "images must be Cloud URLs"}), 400
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
        ("title", "title"), ("description", "description"),
        ("tech_stack", "tech_stack"), ("github_link", "github_link"),
        ("live_demo", "live_demo"), ("cover_image", "project_image"),
    ]:
        if field in payload:
            cleaned = (payload.get(field) or "").strip() or None
            if field == "cover_image" and cleaned and not cleaned.startswith("http"):
                return jsonify({"error": "cover_image must be a Cloud URL"}), 400
            setattr(project, attr, cleaned)

    if "images" in payload and isinstance(payload.get("images"), list):
        project.images = []
        for idx, img in enumerate((payload.get("images") or [])[:6]):
            img_val = (img or "").strip()
            if img_val and not img_val.startswith("http"):
                return jsonify({"error": "images must be Cloud URLs"}), 400
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


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if "admin_logged_in" in session:
        return redirect(url_for("admin"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin_logged_in"] = True
            flash("Logged in successfully!", "success")
            next_page = request.args.get("next")
            return redirect(next_page) if next_page else redirect(url_for("admin"))
        flash("Invalid username or password.", "error")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Logged out successfully!", "success")
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

@app.route("/admin")
@login_required
def admin():
    return render_template(
        "admin.html",
        projects=get_projects(),
        certifications=get_certifications(),
        skills=get_skills(),
        experience=get_experience(),
        profile=get_profile(),
        about_content=get_about_content(),
        about_intro=get_about_intro(),
        about_interests=get_about_interests(),
        highlights=get_highlights(),
    )


# ---------------------------------------------------------------------------
# Admin — certifications
# ---------------------------------------------------------------------------

@app.route("/admin/certifications", methods=["GET", "POST"])
@login_required
def admin_certifications():
    if request.method == "POST":
        title    = request.form.get("title", "").strip()
        platform = request.form.get("platform", "").strip()
        year     = request.form.get("year", "").strip()
        file     = request.files.get("certificate")

        if not title or not platform or not year or not file:
            flash("All fields are required.", "error")
            return redirect(url_for("admin_certifications"))

        if file and allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
            stored_value = _cloudinary_upload(file, "portfolio/certificates", resource_type="raw")
            db.session.add(models.Certification(
                title=title, platform=platform, year=year, certificate_file=stored_value,
            ))
            db.session.commit()
            flash("Certification added successfully!", "success")
            return redirect(url_for("admin_certifications"))

        flash("Please upload a valid PDF file.", "error")
        return redirect(url_for("admin_certifications"))

    return render_template("admin_certifications.html", certifications=get_certifications())


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
    flash("Certification deleted.", "success")
    return redirect(url_for("admin_certifications"))


# ---------------------------------------------------------------------------
# Admin — projects
# ---------------------------------------------------------------------------

@app.route("/admin/projects", methods=["GET", "POST"])
@login_required
def admin_projects():
    if request.method == "GET":
        return redirect(url_for("admin"))

    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    tech_stack  = request.form.get("tech_stack", "").strip()
    github_link = request.form.get("github_link", "").strip()
    live_demo   = request.form.get("live_demo", "").strip()
    files       = request.files.getlist("project_images")

    if not title or not description:
        flash("Title and description are required.", "error")
        return redirect(url_for("admin"))

    valid_files = [f for f in files if f and f.filename and allowed_file(f.filename, ALLOWED_EXTENSIONS_IMG)]

    if len(valid_files) > 6:
        flash("You can upload a maximum of 6 images per project.", "error")
        return redirect(url_for("admin"))

    project = models.Project(
        title=title, description=description, tech_stack=tech_stack,
        github_link=github_link, project_image=None, live_demo=live_demo,
    )
    db.session.add(project)
    db.session.flush()

    if valid_files:
        saved = [_cloudinary_upload(f, f"portfolio/projects/project_{project.id}") for f in valid_files]
        project.project_image = saved[0]
        for idx, rel_path in enumerate(saved):
            db.session.add(models.ProjectImage(project_id=project.id, image_file=rel_path, sort_order=idx))

    db.session.commit()
    flash("Project added successfully!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/projects/manage")
@login_required
def admin_projects_manage():
    return render_template("admin_projects.html", projects=get_projects())


@app.route("/admin/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    project = db.session.get(models.Project, project_id)
    if not project:
        flash("Project not found.", "error")
        return redirect(url_for("admin_projects_manage"))

    image_files = [img.image_file for img in (project.images or []) if img and img.image_file]
    cover = (project.project_image or "").strip()
    if cover and cover not in image_files:
        image_files.append(cover)

    db.session.delete(project)
    db.session.commit()

    for rel in image_files:
        _cloudinary_delete(rel)

    flash("Project deleted.", "success")
    return redirect(url_for("admin_projects_manage"))


# ---------------------------------------------------------------------------
# Admin — project thumbnails
# ---------------------------------------------------------------------------

@app.route("/admin/project_thumbnails", methods=["POST"])
@login_required
def admin_project_thumbnails_add():
    title      = request.form.get("title", "").strip()
    file       = request.files.get("thumbnail_image")
    sort_order = request.form.get("sort_order", "0").strip()

    if not title:
        flash("Thumbnail title is required.", "error")
        return redirect(url_for("admin"))

    if not file or not file.filename or not allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG):
        flash("Please upload a valid thumbnail image.", "error")
        return redirect(url_for("admin"))

    try:
        sort_order_val = int(sort_order)
    except ValueError:
        sort_order_val = 0

    stored_value = _cloudinary_upload(file, "portfolio/project_thumbnails")
    db.session.add(models.ProjectThumbnail(title=title, image_file=stored_value, sort_order=sort_order_val))
    db.session.commit()
    flash("Project thumbnail added.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/project_thumbnails/manage")
@login_required
def admin_project_thumbnails_manage():
    return render_template("admin_project_thumbnails.html", thumbnails=get_project_thumbnails())


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
    flash("Thumbnail deleted.", "success")
    return redirect(url_for("admin_project_thumbnails_manage"))


# ---------------------------------------------------------------------------
# Admin — skills
# ---------------------------------------------------------------------------

@app.route("/admin/skills", methods=["GET", "POST"])
@login_required
def admin_skills():
    if request.method == "GET":
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
    return render_template("admin_skills.html", skills=get_skills())


@app.route("/admin/skills/<int:skill_id>/delete", methods=["POST"])
@login_required
def delete_skill(skill_id):
    row = db.session.get(models.Skill, skill_id)
    if row:
        db.session.delete(row)
        db.session.commit()
    flash("Skill deleted.", "success")
    return redirect(url_for("admin_skills_manage"))


# ---------------------------------------------------------------------------
# Admin — experience
# ---------------------------------------------------------------------------

@app.route("/admin/experience", methods=["GET", "POST"])
@login_required
def admin_experience():
    if request.method == "GET":
        return redirect(url_for("admin_experience_manage"))

    role         = request.form.get("role", "").strip()
    organization = request.form.get("organization", "").strip()
    duration     = request.form.get("duration", "").strip()
    description  = request.form.get("description", "").strip()
    file         = request.files.get("experience_file")

    if not role or not organization or not duration or not description:
        flash("All fields are required.", "error")
        return redirect(url_for("admin"))

    experience_filename = ""
    if file and file.filename:
        if not allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
            flash("Invalid file type. Please upload a PDF.", "error")
            return redirect(url_for("admin"))
        experience_filename = _cloudinary_upload(file, "portfolio/experience", resource_type="raw")

    db.session.add(models.Experience(
        role=role, organization=organization, duration=duration,
        description=description, experience_file=experience_filename,
    ))
    db.session.commit()
    flash("Experience added successfully!", "success")
    return redirect(url_for("admin"))


@app.route("/admin/experience/manage")
@login_required
def admin_experience_manage():
    return render_template("admin_experience.html", experience=get_experience())


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
    flash("Experience deleted.", "success")
    return redirect(url_for("admin_experience_manage"))


# ---------------------------------------------------------------------------
# Admin — profile
# ---------------------------------------------------------------------------

@app.route("/admin/profile", methods=["GET", "POST"])
@login_required
def admin_profile():
    if request.method == "GET":
        return redirect(url_for("update_profile"))

    name     = request.form.get("name", "").strip()
    title    = request.form.get("title", "").strip()
    about    = request.form.get("about", "").strip()
    email    = request.form.get("email", "").strip()
    github   = request.form.get("github", "").strip()
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


@app.route("/update_profile")
@login_required
def update_profile():
    return render_template("update_profile.html", profile=get_profile())


@app.route("/upload_resume", methods=["GET", "POST"])
@login_required
def upload_resume():
    if request.method == "POST":
        file = request.files.get("resume")
        if not file or file.filename == "":
            flash("No file selected.", "error")
            return redirect(url_for("admin"))
        if not allowed_file(file.filename, ALLOWED_EXTENSIONS_PDF):
            flash("Invalid file type. Only PDF files are allowed.", "error")
            return redirect(url_for("admin"))

        # FIX 8: Delete the old resume from Cloudinary before uploading the
        # new one, to avoid orphaned files accumulating in your Cloudinary account.
        profile = db.session.get(models.Profile, 1)
        old_resume = (profile.resume_file if profile else "") or ""
        if old_resume:
            _cloudinary_delete(old_resume)

        stored_value = _cloudinary_upload(file, "portfolio/resume", resource_type="raw")
        if profile is None:
            profile = models.Profile(id=1)
            db.session.add(profile)
        profile.resume_file = stored_value
        db.session.commit()
        flash("Resume uploaded successfully!", "success")
        return redirect(url_for("admin"))

    return render_template("upload_resume.html", profile=get_profile())


@app.route("/upload_profile_image", methods=["GET", "POST"])
@login_required
def upload_profile_image():
    if request.method == "POST":
        file = request.files.get("profile_image")
        if not file or file.filename == "":
            flash("No file selected.", "error")
            return redirect(url_for("admin"))
        if not allowed_file(file.filename, ALLOWED_EXTENSIONS_IMG):
            flash("Invalid file type. Only image files are allowed.", "error")
            return redirect(url_for("admin"))

        profile = db.session.get(models.Profile, 1)
        old_image = (profile.profile_image if profile else "") or ""
        if old_image:
            _cloudinary_delete(old_image)

        stored_value = _cloudinary_upload(file, "portfolio/profile")
        if profile is None:
            profile = models.Profile(id=1)
            db.session.add(profile)
        profile.profile_image = stored_value
        db.session.commit()
        flash("Profile image uploaded successfully!", "success")
        return redirect(url_for("admin"))

    return render_template("upload_profile_image.html")


# ---------------------------------------------------------------------------
# Admin — about
# ---------------------------------------------------------------------------

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
    headline   = request.form.get("headline", "").strip()
    role_line  = request.form.get("role_line", "").strip()
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

    # FIX 9: Delete the old about image before uploading a new one.
    row = db.session.get(models.AboutIntro, 1)
    old_about_image = (row.about_image if row else "") or ""
    if old_about_image:
        _cloudinary_delete(old_about_image)

    stored_value = _cloudinary_upload(file, "portfolio/about")

    if row is None:
        row = models.AboutIntro(id=1, headline="", role_line="", short_desc="", about_image="")
        db.session.add(row)
    row.about_image = stored_value

    # FIX 10: This block (syncing project cover images into ProjectImage rows)
    # was placed inside admin_about_image, which is wrong — it has nothing to
    # do with uploading an about photo. Moved to a dedicated admin utility route
    # below (/admin/sync_project_covers) so it doesn't run on every about-image
    # upload and accidentally create duplicate ProjectImage rows.

    db.session.commit()
    flash("About section image updated.", "success")
    return redirect(url_for("admin"))


# FIX 10 cont.: Dedicated sync route for project cover → ProjectImage migration.
# Run this ONCE after migrating to the new schema, then you can ignore it.
@app.route("/admin/sync_project_covers", methods=["POST"])
@login_required
def admin_sync_project_covers():
    count = 0
    for p in models.Project.query.filter(models.Project.project_image.isnot(None)).all():
        cover = (p.project_image or "").strip()
        if not cover:
            continue
        exists = any((img.image_file or "") == cover for img in (p.images or []))
        if not exists:
            db.session.add(models.ProjectImage(project_id=p.id, image_file=cover, sort_order=0))
            count += 1
    db.session.commit()
    flash(f"Synced {count} project cover image(s) into ProjectImage table.", "success")
    return redirect(url_for("admin"))


# ---------------------------------------------------------------------------
# Admin — interests
# ---------------------------------------------------------------------------

@app.route("/admin/interests", methods=["POST"])
@login_required
def admin_interests_add():
    label       = request.form.get("label", "").strip()
    count_value = request.form.get("count_value", "0").strip()
    sort_order  = request.form.get("sort_order", "0").strip()

    if not label:
        flash("Interest label is required.", "error")
        return redirect(url_for("admin"))

    try:
        count_value_int = int(count_value)
    except ValueError:
        count_value_int = 0
    try:
        sort_order_int = int(sort_order)
    except ValueError:
        sort_order_int = 0

    db.session.add(models.AboutInterest(label=label, count_value=count_value_int, sort_order=sort_order_int))
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


# ---------------------------------------------------------------------------
# Admin — highlights
# ---------------------------------------------------------------------------

@app.route("/admin/highlights", methods=["POST"])
@login_required
def admin_highlights():
    icon_key    = request.form.get("icon_key", "").strip()
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    sort_order  = request.form.get("sort_order", "0").strip()

    if not title or not description:
        flash("Highlight title and description are required.", "error")
        return redirect(url_for("admin"))

    try:
        sort_order_int = int(sort_order)
    except ValueError:
        sort_order_int = 0

    db.session.add(models.Highlight(
        icon_key=icon_key, title=title, description=description, sort_order=sort_order_int,
    ))
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


# ---------------------------------------------------------------------------
# Legacy / disabled
# ---------------------------------------------------------------------------

@app.route("/uploads/<path:_path>")
def uploads_disabled(_path: str):
    abort(410)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)