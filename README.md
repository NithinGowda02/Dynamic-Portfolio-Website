# 🌐 Dynamic Portfolio Website

> A full-stack, database-driven portfolio website built with Flask and PostgreSQL, with a secure custom admin dashboard for managing every section of the site without touching code.

**🔗 Live Demo:** [dynamic-portfolio-website-wc96.onrender.com](https://dynamic-portfolio-website-wc96.onrender.com/)

---

## 📖 Overview

This is a personal portfolio website built to go beyond a static template — every piece of content (profile info, about section, projects, skills, experience, certifications, highlights, interests) is stored in a PostgreSQL database and rendered dynamically. A custom, secured admin panel lets the site owner update content live, from anywhere, without redeploying code.

The project was built end-to-end — schema design, authentication, cloud file storage, a REST-style JSON API, and production deployment — as a hands-on exercise in real-world backend engineering.

---

## ✨ Features

### 🌍 Public Pages
Dynamically rendered Home, About, Projects, Skills, Experience, Certifications, and Contact pages — all content pulled live from the database.

### 🔐 Secure Admin Authentication
- Hashed password authentication (Werkzeug) — no plaintext credentials
- Hidden, non-guessable admin login route
- Session-based access control via a custom `login_required` decorator

### 🛠️ Full Admin Dashboard (CRUD)
Manage every section of the site from one panel:
- Profile (name, title, about, contact, social links)
- About section (preview text, full details, intro headline, image)
- Highlights / capability cards (icon, title, description, sort order)
- Interests
- Skills
- Work experience (with optional PDF attachment)
- Certifications (with PDF upload)
- Projects (title, description, tech stack, links, up to 6 images each)
- Resume and profile photo upload

### ☁️ Cloud-Based File Storage
All uploads (resume, profile photo, certificates, project images, about image) are stored on **Cloudinary** — not the local filesystem — making the app safe to run on ephemeral hosts like Render where local storage doesn't persist.

### 🔌 REST-style JSON API
`/api/projects` supports `GET`, `POST`, `PUT`, and `DELETE` for programmatic project management, with image URL validation built in.

### ✉️ Contact Form
Server-side validated contact form that sends email notifications via the **Resend API**.

### 🗄️ Production-Ready Database Handling
Tuned specifically for **Neon's serverless PostgreSQL**:
- `pool_pre_ping` — tests connections before use, auto-reconnects if dropped
- `pool_recycle` — recycles connections every 280s to beat Neon's free-tier idle timeout
- Limited pool size / overflow to respect Neon's free-tier connection cap
- Mandatory SSL connection

### 🧭 Reverse Proxy Aware
Uses `ProxyFix` middleware so HTTPS/host detection works correctly behind Render's reverse proxy.

### 🚀 Zero-Touch Bootstrapping
On first run, the app automatically creates all database tables and seeds default rows for content sections — no manual migration step needed for a fresh deploy.

---

## 🛠️ Tech Stack

**Backend**
- Python, Flask
- SQLAlchemy, Flask-Migrate (Alembic)

**Database**
- PostgreSQL (Neon — serverless)

**Storage**
- Cloudinary (images, PDFs)

**Email**
- Resend API

**Frontend**
- HTML, CSS, JavaScript, Jinja2

**Deployment**
- Render, Gunicorn, ProxyFix

---

## 🔄 Architecture Overview

```
Browser
   ↓
Flask routes (public + /admin + /api)
   ↓
login_required (session-based auth) → admin-only routes
   ↓
SQLAlchemy models ←→ PostgreSQL (Neon)
   ↓
Cloudinary (file uploads: resume, images, certificates)
   ↓
Resend API (contact form emails)
```

---

## 🚀 Getting Started

```bash
# Clone the repository
git clone <repository-url>
cd dynamic-portfolio-website

# Install dependencies
pip install -r requirements.txt

# Set environment variables (.env)
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://...
CLOUDINARY_URL=cloudinary://api_key:api_secret@cloud_name
ADMIN_USERNAME=your-username
ADMIN_PASSWORD=your-password
RESEND_API_KEY=your-resend-key

# Run database migrations
flask db upgrade

# Start the application
python app.py
```

Admin panel: `/nkp-secure/login` (configurable via environment).

---

## 📌 Notes

- `SECRET_KEY` and `ADMIN_PASSWORD` must always be set via environment variables in production — the code raises a clear warning if left on insecure defaults.
- File uploads require a valid `CLOUDINARY_URL`; there is no local filesystem fallback by design, to keep the app safe on ephemeral hosting.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome. Feel free to fork the repo and submit a pull request.

---

## 📄 License

This project is licensed under the MIT License.
