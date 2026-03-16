# Nithin.dev Portfolio (Flask + SQLite)

This is a dynamic developer portfolio website built with Flask, SQLite, HTML, CSS, and JavaScript.

## Project Structure

```
d:\Portfolio_website
  app.py
  requirements.txt
  data\
    portfolio.db
    portfolio_live.db            # optional fallback copy (auto-used if primary DB gets stuck)
  uploads\
    about\
    certificates\
    profile\
    projects\
    project_images\              # legacy support
    project_thumbnails\
    resume\
  templates\
    base.html
    home.html
    about.html
    projects.html
    skills.html
    experience.html
    certifications.html
    contact.html
    admin*.html
  static\
    css\
    js\
    images\
  scripts\
    verify_project.py            # automated verification script
```

## Run Locally

```powershell
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000/`.

## Database

The app uses `data/portfolio.db` by default.

If you want to point at a different DB file name inside `data/`, set:

```powershell
$env:PORTFOLIO_DB="portfolio.db"
```

## Verification

Run an automated smoke test (routes + admin inserts + sliders render):

```powershell
python -B scripts\verify_project.py
```

Set `VERIFY_KEEP=1` to keep the inserted test data.

## Cleanup (Optional)

To archive old/unused files into `archive/<today>/cleanup_dump`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\cleanup.ps1
```

To delete instead of archiving:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\cleanup.ps1 -Purge
```
