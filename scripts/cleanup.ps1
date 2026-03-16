$ErrorActionPreference = "Stop"

param(
  [switch]$Purge
)

Write-Host "This script archives (or deletes) legacy / test files created during development." -ForegroundColor Cyan
Write-Host "Default behavior: MOVE to archive/ (safer). Use -Purge to delete." -ForegroundColor Cyan
Write-Host "Review the list carefully before continuing." -ForegroundColor Cyan
Write-Host ""

$paths = @(
  # Legacy templates (not used by app.py routes)
  "templates/index.html",
  "templates/index_singlepage.html",

  # Legacy static folder (app serves static/ now)
  "static_public",

  # Old DB/test files in project root (app uses data/portfolio.db now)
  "database.db",
  "database.db-journal",
  "database_backup.db",
  "database_backup.db-journal",
  "database_fixed.db",
  "database_fixed.db-journal",
  "database_recovered.db",
  "database_recovered.db-journal",
  "portfolio.db",
  "portfolio_data.db",
  "portfolio_data.db-journal",
  "new1.db",
  "new1.db-journal",
  "offtest.db",
  "plain.db",
  "tmp_test.db",
  "tmp_test.db-journal",
  "waltest.db",
  "waltest.db-journal",
  "workaround.db",

  # Misc test artifacts
  "__delete_test__.txt",
  "ps_write_test.txt",
  "py_write_test.txt",
  "check_db.py",
  "verify_project.py",

  # Static mistakes (DB files should never live in /static)
  "static/new3.db",
  "static/new3.db-journal",

  # Upload mistakes (keep real uploads; remove only known junk files)
  "uploads/new2.db",
  "uploads/new2.db-journal",
  "uploads/profile.jpg",
  "uploads/resume.pdf",
  "uploads/certificates/*verify.pdf"
)

Write-Host "Planned targets:" -ForegroundColor Yellow
$paths | ForEach-Object { Write-Host " - $_" }
Write-Host ""

$archiveRoot = Join-Path "archive" (Get-Date -Format "yyyy-MM-dd")
$archiveDest = Join-Path $archiveRoot "cleanup_dump"
New-Item -ItemType Directory -Force $archiveDest | Out-Null

$modeText = if ($Purge) { "DELETE" } else { "MOVE to $archiveDest" }
$answer = Read-Host "Type YES to $modeText these paths"
if ($answer -ne "YES") {
  Write-Host "Aborted." -ForegroundColor Yellow
  exit 0
}

foreach ($p in $paths) {
  if (-not (Test-Path $p)) { continue }

  if ($Purge) {
    Write-Host "Deleting $p"
    Remove-Item -Force -Recurse $p
    continue
  }

  # Move to archive; if wildcard is used, move matching items individually.
  $items = Get-Item $p -ErrorAction SilentlyContinue
  if (-not $items) {
    $items = Get-ChildItem $p -ErrorAction SilentlyContinue
  }
  foreach ($it in $items) {
    $rel = $it.FullName.Substring((Get-Location).Path.Length).TrimStart("\")
    $dest = Join-Path $archiveDest $rel
    $destDir = Split-Path $dest -Parent
    New-Item -ItemType Directory -Force $destDir | Out-Null
    Write-Host "Archiving $rel"
    Move-Item -Force $it.FullName $dest
  }
}

Write-Host "Cleanup complete." -ForegroundColor Green
