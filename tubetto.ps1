# Tubetto Django Application Startup Script (PowerShell Version)
$ErrorActionPreference = "Stop"

# Helper per l'output colorato
function Write-Info ($Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Success ($Message) { Write-Host "[SUCCESS] $Message" -ForegroundColor Green }
function Write-ErrorCustom ($Message) { Write-Host "[ERROR] $Message" -ForegroundColor Red }

# Definizione dei percorsi usando la directory dello script
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PROJECT_ROOT = Join-Path $SCRIPT_DIR "tubetto"
$VENV_PATH = Join-Path $SCRIPT_DIR "env\dev"
$ENV_FILE = Join-Path $SCRIPT_DIR "tubetto.env"

# Configurazione di default (se non già definite nell'ambiente)
if (-not $env:DJANGO_SETTINGS_MODULE) { $env:DJANGO_SETTINGS_MODULE = "tubetto.settings" }
$DJANGO_PORT = if ($env:DJANGO_PORT) { $env:DJANGO_PORT } else { "8000" }
$DJANGO_HOST = if ($env:DJANGO_HOST) { $env:DJANGO_HOST } else { "127.0.0.1" }

# 1. Controllo ed attivazione del Virtual Environment
$VENV_ACTIVATE = Join-Path $VENV_PATH "Scripts\Activate.ps1"
if (-not (Test-Path $VENV_ACTIVATE)) {
    Write-ErrorCustom "Virtual environment non trovato in: $VENV_PATH"
    Write-Info "Per crearlo, esegui: python -m venv $VENV_PATH"
    Exit 1
}

Write-Info "Attivazione del virtual environment..."
& $VENV_ACTIVATE
Write-Success "Virtual environment attivato"

# 2. Caricamento delle variabili d'ambiente dal file .env
if (-not (Test-Path $ENV_FILE)) {
    Write-ErrorCustom "File d'ambiente $ENV_FILE non trovato."
    Exit 1
}

Write-Info "Caricamento delle variabili d'ambiente..."
Get-Content $ENV_FILE | ForEach-Object {
    $line = $_.Trim()
    # Salta le righe vuote e i commenti
    if ($line -and -not $line.StartsWith("#")) {
        # Separa alla prima occorrenza di '='
        if ($line -match '^([^=]+)=(.*)$') {
            $key = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            # Rimuove eventuali virgolette esterne dal valore
            $value = $value -replace '^["'']|["'']$', ''
            [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}
Write-Success "Variabili d'ambiente caricate con successo."

# 3. Avvio di Django Runserver
Set-Location $PROJECT_ROOT

# Corretto l'uso delle graffe per evitare conflitti con i due punti (:)
Write-Info "Avvio del server di sviluppo Django su ${DJANGO_HOST}:${DJANGO_PORT}..."
Write-Info "Settings: $env:DJANGO_SETTINGS_MODULE"
Write-Success "L'applicazione Tubetto Django è pronta!"
Write-Host ""
Write-Host "- In ascolto su: http://${DJANGO_HOST}:${DJANGO_PORT}"
Write-Host "- Admin panel: http://${DJANGO_HOST}:${DJANGO_PORT}/admin"
Write-Host ""

python manage.py runserver "${DJANGO_HOST}:${DJANGO_PORT}"