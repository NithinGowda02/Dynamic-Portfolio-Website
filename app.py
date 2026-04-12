import os
import re
from functools import wraps

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from db_config import get_database_uri
from extensions import db, migrate

# ---------------------------------------------------------------------------
# CLOUDINARY (OPTIONAL — now supports GitHub RAW also)
# ---------------------------------------------------------------------------
try:
    import cloudinary
    import cloudinary.uploader

    cloudinary.config(secure=True)

    CLOUDINARY_ENABLED = bool(
        os.environ.get("CLOUDINARY_URL")
        and cloudinary.config().cloud_name
    )
except ImportError:
    cloudinary = None
    CLOUDINARY_ENABLED = False


def upload_file(file_obj, folder: str, resource_type: str = "auto") -> str:
    """Upload file to Cloudinary (if enabled)"""
    if not CLOUDINARY_ENABLED:
        return ""

    result = cloudinary.uploader.upload(
        file_obj,
        folder=folder,
        resource_type=resource_type,
        use_filename=True,
        unique_filename=True,
        overwrite=False,
    )
    return (result or {}).get("secure_url", "")


def delete_file(url: str) -> None:
    """Delete Cloudinary file safely"""
    if not CLOUDINARY_ENABLED or not url:
        return

    try:
        match = re.search(r"/upload/(?:v\d+/)?(.+?)(?:\.[a-zA-Z0-9]+)?$", url)
        if match:
            cloudinary.uploader.destroy(match.group(1))
    except Exception as e:
        print(f"[WARN] Delete failed: {e}")


# ---------------------------------------------------------------------------
# APP INIT
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# Proxy fix (Render / production)
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Disable static cache
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


# ---------------------------------------------------------------------------
# AUTH CONFIG
# ---------------------------------------------------------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD_HASH = generate_password_hash("admin123")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin_logged_in" not in session:
            flash("Please login first", "error")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# DATABASE CONFIG
# ---------------------------------------------------------------------------
database_url = get_database_uri()

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate.init_app(app, db)

import models  # noqa


with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# FILE VALIDATION
# ---------------------------------------------------------------------------
ALLOWED_PDF = {"pdf"}
ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "svg"}


def allowed_file(filename, allowed_ext):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_ext


def is_valid_url(value):
    return isinstance(value, str) and value.startswith("http")


# ---------------------------------------------------------------------------
# CONTEXT PROCESSORS
# ---------------------------------------------------------------------------
@app.context_processor
def inject_asset_url():
    def asset_url(value: str) -> str:
        if not value:
            return ""
        if value.startswith("http"):
            return value  # ✅ GitHub RAW + Cloudinary supported
        return ""
    return {"asset_url": asset_url}


@app.context_processor
def inject_static_version():
    try:
        css = os.path.join(app.static_folder, "css", "style.css")
        js = os.path.join(app.static_folder, "js", "main.js")
        v = int(max(os.path.getmtime(css), os.path.getmtime(js)))
    except:
        v = 1
    return {"static_v": v}


# ---------------------------------------------------------------------------
# DATA HELPERS
# ---------------------------------------------------------------------------
def get_certifications():
    rows = models.Certification.query.order_by(models.Certification.id.desc()).all()
    return [(c.id, c.title, c.platform, c.year, c.certificate_file) for c in rows]


def get_experience():
    rows = models.Experience.query.order_by(models.Experience.id.desc()).all()
    return [(e.id, e.role, e.organization, e.duration, e.description, e.experience_file) for e in rows]


def get_profile():
    row = models.Profile.query.first()
    if not row:
        return None
    return (
        row.id, row.name, row.title, row.about,
        row.email, row.github, row.linkedin,
        row.resume_file, row.profile_image,
    )

    # ---------------------------------------------------------------------------
# PUBLIC ROUTES
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    profile = get_profile()
    certifications = get_certifications()
    experience = get_experience()
    projects = models.Project.query.order_by(models.Project.id.desc()).all()

    return render_template(
        "index.html",
        profile=profile,
        certifications=certifications,
        experience=experience,
        projects=projects,
    )


@app.route("/projects")
def projects_page():
    projects = models.Project.query.order_by(models.Project.id.desc()).all()
    return render_template("projects.html", projects=projects)


# ---------------------------------------------------------------------------
# PROJECT API (FOR DYNAMIC FRONTEND)
# ---------------------------------------------------------------------------

@app.route("/api/projects")
def api_projects():
    projects = models.Project.query.order_by(models.Project.id.desc()).all()

    data = []
    for p in projects:
        data.append({
            "id": p.id,
            "title": p.title,
            "description": p.description,
            "tech_stack": p.tech_stack,
            "github": p.github,
            "live_demo": p.live_demo,
            "image": p.image if is_valid_url(p.image) else ""
        })

    return jsonify(data)


# ---------------------------------------------------------------------------
# CONTACT FORM
# ---------------------------------------------------------------------------

@app.route("/contact", methods=["POST"])
def contact():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    message = request.form.get("message", "").strip()

    # Basic validation
    if not name or not email or not message:
        flash("All fields are required!", "error")
        return redirect(url_for("index"))

    if "@" not in email:
        flash("Invalid email address!", "error")
        return redirect(url_for("index"))

    try:
        contact_entry = models.Contact(
            name=name,
            email=email,
            message=message
        )
        db.session.add(contact_entry)
        db.session.commit()

        flash("Message sent successfully!", "success")

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Contact form: {e}")
        flash("Something went wrong. Try again.", "error")

    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# STATIC FILE DEBUG ROUTE (OPTIONAL)
# ---------------------------------------------------------------------------

@app.route("/debug/files")
@login_required
def debug_files():
    certs = get_certifications()
    exps = get_experience()
    profile = get_profile()

    return jsonify({
        "certifications": certs,
        "experience": exps,
        "resume": profile[7] if profile else None
    })


# ---------------------------------------------------------------------------
# ERROR HANDLING
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template("500.html"), 500

# ---------------------------------------------------------------------------
# ADMIN AUTH ROUTES
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["admin_logged_in"] = True
            flash("Login successful!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid credentials!", "error")

    return render_template("admin/login.html")


@app.route("/admin/logout")
@login_required
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Logged out successfully!", "success")
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------------------
# ADMIN DASHBOARD
# ---------------------------------------------------------------------------

@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    return render_template("admin/dashboard.html")


# ---------------------------------------------------------------------------
# ADD CERTIFICATION
# ---------------------------------------------------------------------------

@app.route("/admin/add-certification", methods=["POST"])
@login_required
def add_certification():
    title = request.form.get("title")
    platform = request.form.get("platform")
    year = request.form.get("year")
    file = request.files.get("certificate_file")
    url = request.form.get("certificate_url")

    file_url = ""

    # Priority: File upload > URL
    if file and allowed_file(file.filename, ALLOWED_PDF):
        file_url = upload_file(file, "certificates", resource_type="raw")
    elif is_valid_url(url):
        file_url = url

    try:
        cert = models.Certification(
            title=title,
            platform=platform,
            year=year,
            certificate_file=file_url
        )
        db.session.add(cert)
        db.session.commit()
        flash("Certification added!", "success")
    except Exception as e:
        db.session.rollback()
        print(e)
        flash("Error adding certification", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# DELETE CERTIFICATION
# ---------------------------------------------------------------------------

@app.route("/admin/delete-certification/<int:id>")
@login_required
def delete_certification(id):
    cert = models.Certification.query.get_or_404(id)

    delete_file(cert.certificate_file)

    db.session.delete(cert)
    db.session.commit()

    flash("Deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# ADD EXPERIENCE
# ---------------------------------------------------------------------------

@app.route("/admin/add-experience", methods=["POST"])
@login_required
def add_experience():
    role = request.form.get("role")
    organization = request.form.get("organization")
    duration = request.form.get("duration")
    description = request.form.get("description")

    file = request.files.get("experience_file")
    url = request.form.get("experience_url")

    file_url = ""

    if file and allowed_file(file.filename, ALLOWED_PDF):
        file_url = upload_file(file, "experience", resource_type="raw")
    elif is_valid_url(url):
        file_url = url

    try:
        exp = models.Experience(
            role=role,
            organization=organization,
            duration=duration,
            description=description,
            experience_file=file_url
        )
        db.session.add(exp)
        db.session.commit()
        flash("Experience added!", "success")
    except Exception as e:
        db.session.rollback()
        print(e)
        flash("Error adding experience", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# DELETE EXPERIENCE
# ---------------------------------------------------------------------------

@app.route("/admin/delete-experience/<int:id>")
@login_required
def delete_experience(id):
    exp = models.Experience.query.get_or_404(id)

    delete_file(exp.experience_file)

    db.session.delete(exp)
    db.session.commit()

    flash("Deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# ADD PROJECT
# ---------------------------------------------------------------------------

@app.route("/admin/add-project", methods=["POST"])
@login_required
def add_project():
    title = request.form.get("title")
    description = request.form.get("description")
    tech_stack = request.form.get("tech_stack")
    github = request.form.get("github")
    live_demo = request.form.get("live_demo")

    image = request.files.get("image")
    image_url = request.form.get("image_url")

    final_image = ""

    if image and allowed_file(image.filename, ALLOWED_IMG):
        final_image = upload_file(image, "projects")
    elif is_valid_url(image_url):
        final_image = image_url

    try:
        project = models.Project(
            title=title,
            description=description,
            tech_stack=tech_stack,
            github=github,
            live_demo=live_demo,
            image=final_image
        )
        db.session.add(project)
        db.session.commit()
        flash("Project added!", "success")
    except Exception as e:
        db.session.rollback()
        print(e)
        flash("Error adding project", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# DELETE PROJECT
# ---------------------------------------------------------------------------

@app.route("/admin/delete-project/<int:id>")
@login_required
def delete_project(id):
    project = models.Project.query.get_or_404(id)

    delete_file(project.image)

    db.session.delete(project)
    db.session.commit()

    flash("Deleted successfully", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# UPDATE PROFILE (VERY IMPORTANT)
# ---------------------------------------------------------------------------

@app.route("/admin/update-profile", methods=["POST"])
@login_required
def update_profile():
    profile = models.Profile.query.first()

    if not profile:
        profile = models.Profile()

    profile.name = request.form.get("name")
    profile.title = request.form.get("title")
    profile.about = request.form.get("about")
    profile.email = request.form.get("email")
    profile.github = request.form.get("github")
    profile.linkedin = request.form.get("linkedin")

    # Resume (PDF)
    resume_file = request.files.get("resume_file")
    resume_url = request.form.get("resume_url")

    if resume_file and allowed_file(resume_file.filename, ALLOWED_PDF):
        profile.resume_file = upload_file(resume_file, "resume", resource_type="raw")
    elif is_valid_url(resume_url):
        profile.resume_file = resume_url

    # Profile Image
    image_file = request.files.get("profile_image")
    image_url = request.form.get("profile_image_url")

    if image_file and allowed_file(image_file.filename, ALLOWED_IMG):
        profile.profile_image = upload_file(image_file, "profile")
    elif is_valid_url(image_url):
        profile.profile_image = image_url

    try:
        db.session.add(profile)
        db.session.commit()
        flash("Profile updated!", "success")
    except Exception as e:
        db.session.rollback()
        print(e)
        flash("Error updating profile", "error")

    return redirect(url_for("admin_dashboard"))

# ---------------------------------------------------------------------------
# UPDATE CERTIFICATION
# ---------------------------------------------------------------------------

@app.route("/admin/edit-certification/<int:id>", methods=["POST"])
@login_required
def edit_certification(id):
    cert = models.Certification.query.get_or_404(id)

    cert.title = request.form.get("title")
    cert.platform = request.form.get("platform")
    cert.year = request.form.get("year")

    file = request.files.get("certificate_file")
    url = request.form.get("certificate_url")

    if file and allowed_file(file.filename, ALLOWED_PDF):
        delete_file(cert.certificate_file)
        cert.certificate_file = upload_file(file, "certificates", resource_type="raw")
    elif is_valid_url(url):
        cert.certificate_file = url

    try:
        db.session.commit()
        flash("Certification updated!", "success")
    except Exception as e:
        db.session.rollback()
        print(e)
        flash("Error updating certification", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# UPDATE EXPERIENCE
# ---------------------------------------------------------------------------

@app.route("/admin/edit-experience/<int:id>", methods=["POST"])
@login_required
def edit_experience(id):
    exp = models.Experience.query.get_or_404(id)

    exp.role = request.form.get("role")
    exp.organization = request.form.get("organization")
    exp.duration = request.form.get("duration")
    exp.description = request.form.get("description")

    file = request.files.get("experience_file")
    url = request.form.get("experience_url")

    if file and allowed_file(file.filename, ALLOWED_PDF):
        delete_file(exp.experience_file)
        exp.experience_file = upload_file(file, "experience", resource_type="raw")
    elif is_valid_url(url):
        exp.experience_file = url

    try:
        db.session.commit()
        flash("Experience updated!", "success")
    except Exception as e:
        db.session.rollback()
        print(e)
        flash("Error updating experience", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# UPDATE PROJECT
# ---------------------------------------------------------------------------

@app.route("/admin/edit-project/<int:id>", methods=["POST"])
@login_required
def edit_project(id):
    project = models.Project.query.get_or_404(id)

    project.title = request.form.get("title")
    project.description = request.form.get("description")
    project.tech_stack = request.form.get("tech_stack")
    project.github = request.form.get("github")
    project.live_demo = request.form.get("live_demo")

    image = request.files.get("image")
    image_url = request.form.get("image_url")

    if image and allowed_file(image.filename, ALLOWED_IMG):
        delete_file(project.image)
        project.image = upload_file(image, "projects")
    elif is_valid_url(image_url):
        project.image = image_url

    try:
        db.session.commit()
        flash("Project updated!", "success")
    except Exception as e:
        db.session.rollback()
        print(e)
        flash("Error updating project", "error")

    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# OPTIONAL: SEARCH PROJECTS (READY TO USE)
# ---------------------------------------------------------------------------

@app.route("/api/search-projects")
def search_projects():
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify([])

    projects = models.Project.query.filter(
        models.Project.title.ilike(f"%{query}%")
    ).all()

    data = [{
        "id": p.id,
        "title": p.title,
        "description": p.description
    } for p in projects]

    return jsonify(data)


# ---------------------------------------------------------------------------
# OPTIONAL: PAGINATION (FUTURE READY)
# ---------------------------------------------------------------------------

@app.route("/projects/page/<int:page>")
def paginated_projects(page):
    per_page = 6

    pagination = models.Project.query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    return render_template(
        "projects.html",
        projects=pagination.items,
        pagination=pagination
    )


# ---------------------------------------------------------------------------
# FINAL ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)