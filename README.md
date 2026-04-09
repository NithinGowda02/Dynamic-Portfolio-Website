# 🚀 Nithin.dev Portfolio (Flask + SQLite)

A dynamic and fully customizable **developer portfolio website** built using **Flask, SQLite, HTML, CSS, and JavaScript**.  
This application allows developers to showcase their **projects, skills, experience, and certifications** with a powerful **admin dashboard** for managing content easily.

---

## 🌟 Features

- 🧑‍💻 Personal profile with resume & social links  
- 📂 Project showcase with multiple images & live demo links  
- 🛠️ Skills management  
- 💼 Experience section with file uploads  
- 📜 Certifications with PDF uploads  
- 🖼️ Image uploads (projects, profile, about section)  
- 🔐 Secure admin panel with authentication  
- 📊 Dynamic stats (projects, skills, certifications)  
- 📬 Contact form  
- ⚡ Cache-busting for static assets  
- 🧠 SQLite fallback system for improved reliability  

---

## 🏗️ Tech Stack

**Frontend**
- HTML5
- CSS3
- JavaScript

**Backend**
- Python (Flask)

**Database**
- SQLite

**Tools**
- Werkzeug (security & file handling)
- Jinja2 (templating)

---

## 📁 Project Structure

## Deploying on Render (Fix refresh redirects + missing uploads)

This repo is a **Flask web app**. On Render it should be deployed as a **Web Service** (not a “Static Site”),
otherwise direct navigation / refresh on routes like `/about` or `/projects` can 404 or appear to “redirect/break”.

### Render service settings

- **Environment**: `Python`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`

### Required environment variables

- `FLASK_SECRET`: set a strong random secret (keeps sessions stable across restarts)

### Persistent data (recommended)

If you add/edit content from the admin dashboard, you are writing to:
- an SQLite DB file (skills/projects/etc.)
- the `uploads/` folder (images/PDFs)

On Render, the filesystem is **ephemeral** across deploys unless you attach a **Persistent Disk**. Also, this repo
intentionally keeps `uploads/` out of git (see `.gitignore`), so uploaded images won’t be present on a fresh deploy.

To make your content survive redeploys:

1. Create a **Persistent Disk** in Render and mount it (example mount path: `/var/data`)
2. Set:
   - `PORTFOLIO_STORAGE_DIR=/var/data`
   - `TRUST_PROXY_HEADERS=true`

After that, new uploads and DB writes will go under `/var/data/uploads/` and `/var/data/data/`.

### “My latest skills/projects don’t show after deploy”

Common causes:

- You added content locally but did not commit `data/portfolio.db` (Render only sees what’s pushed to git)
- You uploaded images locally (they are ignored by git via `uploads/`), so they never get deployed
- You redeployed on Render without a persistent disk, so the container started with empty uploads again

### Forcing updates to reflect

In Render: **Manual Deploy → Clear build cache & deploy** if you suspect stale build output.
Browsers can still cache assets aggressively; this app includes static cache-busting, and disables cache for `/static/*`.
