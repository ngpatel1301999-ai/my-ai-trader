# ============================================================================
#  update-vscode.ps1  —  fixed files ko apne VS Code project me copy karta hai
#
#  Kaise chalayein (PowerShell me, ek line):
#
#     Set-ExecutionPolicy -Scope Process Bypass -Force; .\update-vscode.ps1
#
#  Ye script:
#    1. source dhundhti hai (fixed-files\ ya fixed-files.zip se extract hua folder)
#    2. 17 fixed files copy karti hai (purani files ka backup bhi leti hai)
#    3. git status dikhati hai
#
#  Isko REPO ROOT me rakho (jahan .git folder hai), phir chalao.
# ============================================================================

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
Write-Host "Repo root: $root" -ForegroundColor Cyan

# ---- 1. git repo hai ya nahi ----
if (-not (Test-Path ".git")) {
    Write-Warning ".git folder nahi mila. Is script ko 'my-ai-trader' folder me rakho (repo root)."
}

# ---- 2. python check (WindowsApps wala stub asli python nahi hota) ----
$py = $null
foreach ($cand in @("py", "python")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*") { $py = $cand; break }
}
if (-not $py) {
    Write-Warning "Asli Python nahi mila (sirf Windows Store ka stub hai)."
    Write-Warning "Install karo: https://www.python.org/downloads/  -> 'Add python.exe to PATH' TICK karna."
    Write-Warning "Ya Microsoft Store se 'Python 3.12' install karo."
} else {
    Write-Host "Python: $py -> $((Get-Command $py).Source)" -ForegroundColor Green
}

# ---- 3. source folder dhundo ----
$src = $null
foreach ($cand in @("fixed-files", "fixed_files", "extracted", ".")) {
    if (Test-Path (Join-Path $cand "smoke_test.py")) { $src = (Resolve-Path $cand).Path; break }
}
if (-not $src) {
    # zip abhi bhi pada hai? extract kar do
    if (Test-Path "fixed-files.zip") {
        Write-Host "fixed-files.zip mila -> extract kar rahe hain..." -ForegroundColor Yellow
        Expand-Archive -Path "fixed-files.zip" -DestinationPath "fixed-files" -Force
        $src = (Resolve-Path "fixed-files").Path
    }
}
if (-not $src) {
    Write-Host ""
    Write-Host "X  Fixed files nahi mile!" -ForegroundColor Red
    Write-Host "   'fixed-files.zip' (ya extract hua 'fixed-files' folder) ko ISS folder me daalo:" -ForegroundColor Yellow
    Write-Host "   $root" -ForegroundColor Yellow
    Write-Host "   phir script dobara chalao." -ForegroundColor Yellow
    exit 1
}
Write-Host "Source: $src" -ForegroundColor Green

# ---- 4. copy karne wali files ----
$files = @(
    ".gitignore",
    ".python-version",
    "render.yaml",
    "smoke_test.py",
    "RENDER_DEPLOY_FIX.md",
    "kotak-auto-trader/.gitignore",
    "kotak-auto-trader/README.md",
    "kotak-auto-trader/app.py",
    "kotak-auto-trader/commodity.py",
    "kotak-auto-trader/frontend/index.html",
    "kotak-auto-trader/kotak_client.py",
    "kotak-auto-trader/main.py",
    "kotak-auto-trader/memory.py",
    "kotak-auto-trader/paths.py",
    "kotak-auto-trader/requirements.txt",
    "kotak-auto-trader/risk.py",
    "kotak-auto-trader/swing.py",
    "kotak-auto-trader/tasks.py",
    "kotak-auto-trader/telegram_remote.py"
)

# ---- 5. backup ----
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $root "backup-before-fix-$stamp"
New-Item -ItemType Directory -Path $backup -Force | Out-Null

$copied = 0
$missing = @()
foreach ($f in $files) {
    $from = Join-Path $src $f
    $to   = Join-Path $root $f
    if (-not (Test-Path $from)) { $missing += $f; continue }

    # backup (agar purani file hai)
    if (Test-Path $to) {
        $b = Join-Path $backup $f
        New-Item -ItemType Directory -Path (Split-Path $b -Parent) -Force | Out-Null
        Copy-Item $to $b -Force
    }
    New-Item -ItemType Directory -Path (Split-Path $to -Parent) -Force | Out-Null
    Copy-Item $from $to -Force
    Write-Host "  copied  $f"
    $copied++
}

Write-Host ""
Write-Host "=================== RESULT ===================" -ForegroundColor Cyan
Write-Host "Copied : $copied files"
Write-Host "Backup : $backup"
if ($missing.Count) {
    Write-Warning "Source me ye files nahi mile (skip): $($missing -join ', ')"
}

# ---- 6. git status ----
$git = Get-Command git -ErrorAction SilentlyContinue
if ((Test-Path ".git") -and $git) {
    Write-Host ""
    Write-Host "--- git status ---" -ForegroundColor Cyan
    git status --short
} elseif (-not $git) {
    Write-Warning "git install nahi hai -> https://git-scm.com/download/win"
}

Write-Host ""
Write-Host "Ab ye 4 commands chalao:" -ForegroundColor Green
Write-Host "  cd kotak-auto-trader; pip install -r requirements.txt; cd .."
Write-Host "  py smoke_test.py        (ya: python smoke_test.py)"
Write-Host "  git add -A"
Write-Host '  git commit -m "Fix Render deploy: app/App clash, duplicate FastAPI app, assistant mode, Python 3.12, DATA_DIR"'
Write-Host "  git push origin main"
