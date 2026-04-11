import os


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

    _CLOUDINARY_ENABLED = bool(os.environ.get("CLOUDINARY_URL"))

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
    """Upload *file_obj* to Cloudinary and return the secure URL."""
    _require_cloudinary()
    result = cloudinary.uploader.upload(
        file_obj,
        folder=folder,
        resource_type=resource_type,
        overwrite=True,
    )
    url = (result or {}).get("secure_url")
    if not url:
        raise RuntimeError("Cloudinary upload succeeded but no secure_url was returned.")
    return url


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

ALLOWED_EXTENSIONS_PDF = {"pdf"}
ALLOWED_EXTENSIONS_IMG = {"png", "jpg", "jpeg", "gif", "svg"}


# ---------------------------------------------------------------------------
# Database (PostgreSQL via DATABASE_URL only)
# ---------------------------------------------------------------------------
app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db.init_app(app)
migrate.init_app(app, db)

# Register ORM models for Flask-Migrate / SQLAlchemy.
import models  # noqa: E402

_AUTO_DB_CREATE = os.environ.get("AUTO_DB_CREATE", "").strip().lower() in {"1", "true", "yes"}
if not os.environ.get("AUTO_DB_CREATE", "").strip():
    # Safe default: create tables if they don't exist yet.
    # For mature deployments, set AUTO_DB_CREATE=false and run migrations instead.
    _AUTO_DB_CREATE = True

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
def inject_asset_url():
    def asset_url(value: str) -> str:
        """
        Return a Cloudinary URL stored in the DB.

        This app no longer supports local /uploads paths. Any non-URL value indicates stale data
        that must be re-uploaded to Cloudinary (and the DB updated to store secure_url).
        """
        if not value:
            return ""
        if value.startswith("http"):
            return value
        # Stale data from older deployments may contain local paths/filenames.
        # We intentionally do not try to serve from disk in production.
        return ""

    return {"asset_url": asset_url}


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
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    tech_stack = (payload.get("tech_stack") or "").strip()
    github_link = (payload.get("github_link") or "").strip()
    live_demo = (payload.get("live_demo") or "").strip()
    cover_image = (payload.get("cover_image") or "").strip() or None

    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400

    if cover_image and not cover_image.startswith("http"):
        return jsonify({"error": "cover_image must be a Cloud URL"}), 400

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
        ("title", "title"),
        ("description", "description"),
        ("tech_stack", "tech_stack"),
        ("github_link", "github_link"),
        ("live_demo", "live_demo"),
        ("cover_image", "project_image"),
    ]:
        if field in payload:
            value = payload.get(field)
            cleaned = (value or "").strip() or None
            if field == "cover_image" and cleaned and not cleaned.startswith("http"):
                return jsonify({"error": "cover_image must be a Cloud URL"}), 400
            setattr(project, attr, cleaned)

    if "images" in payload and isinstance(payload.get("images"), list):
        # Replace image list (max 6).
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
            stored_value = _cloudinary_upload(file, "portfolio/certificates", resource_type="raw")

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
            stored_value = _cloudinary_upload(file, "portfolio/certificates", resource_type="raw")

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
        saved = []
        for f in valid_files:
            saved.append(_cloudinary_upload(f, f"portfolio/projects/{project_folder_name}"))

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

    stored_value = _cloudinary_upload(file, "portfolio/project_thumbnails")

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

        experience_filename = _cloudinary_upload(file, "portfolio/experience", resource_type="raw")

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

            experience_filename = _cloudinary_upload(file, "portfolio/experience", resource_type="raw")

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

    stored_value = _cloudinary_upload(file, "portfolio/about")

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

        stored_value = _cloudinary_upload(file, "portfolio/resume", resource_type="raw")

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

        stored_value = _cloudinary_upload(file, "portfolio/profile")

        if profile is None:
            profile = models.Profile(id=1)
            db.session.add(profile)
        profile.profile_image = stored_value
        db.session.commit()

        flash("Profile image uploaded successfully!", "success")
        return redirect(url_for("admin"))

    return render_template("upload_profile_image.html")





@app.route("/uploads/<path:_path>")
def uploads_disabled(_path: str):
    # Legacy URL path from older versions. Local filesystem storage is no longer supported.
    abort(410)


if __name__ == "__main__":
    # Enable the reloader in development so templates/routes stay in sync.
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True)
