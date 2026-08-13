# =============================================================================
#  Done.ai Support Assistant — installasjon
# =============================================================================
#  Trygg a kjore om igjen. Overskriver aldri config.env, secrets\ eller en
#  CLAUDE.md du har endret selv.
# =============================================================================

param(
    [switch] $SkipPackageUpgrade,
    # Hvor saksmappene med kundedata skal ligge. Utenfor repoet.
    [string] $AutoXsaleDir,
    # Mappen du apner i Claude Code. Standard: repoets egen mappe.
    [string] $ProjectRoot
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

function Trinn([string] $t) { Write-Host "`n>> $t" -ForegroundColor Cyan }

Trinn "Kontrollerer settet"
Assert-KitLayout
Write-Host "  Settet ligger i: $($script:KitRoot)"

# --- Python -----------------------------------------------------------------
Trinn "Python"
$python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $python) {
    throw ("Python ble ikke funnet i PATH.`n" +
        "Installer Python 3.10 eller nyere, og huk av for 'Add python.exe to PATH'.")
}
$ver = (& $python.Source --version 2>&1 | Out-String).Trim()
Write-Host "  $ver  ($($python.Source))"
if ($ver -match "(\d+)\.(\d+)") {
    $major = [int]$Matches[1]; $minor = [int]$Matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        throw "Python 3.10 eller nyere kreves. Fant $ver."
    }
}

# --- Virtuelt miljo ---------------------------------------------------------
Trinn "Virtuelt Python-miljo"
$venvOk = $false
if (Test-Path -LiteralPath $script:VenvPython) {
    # Test-Path alene er ikke nok: et venv kopiert fra en annen maskin har den
    # opprinnelige interpreteren bakt inn i pyvenv.cfg og feiler ved kjoring.
    try {
        & $script:VenvPython -c "import sys; sys.exit(0)" 2>&1 | Out-Null
        $venvOk = ($LASTEXITCODE -eq 0)
    } catch { $venvOk = $false }
    if (-not $venvOk) {
        Write-Warning "  Eksisterende .venv virker ikke (sannsynligvis kopiert fra en annen maskin). Bygger pa nytt."
        Remove-Item -Recurse -Force -LiteralPath $script:VenvRoot
    }
}
if (-not $venvOk) {
    & $python.Source -m venv $script:VenvRoot
    Write-Host "  Opprettet $($script:VenvRoot)"
} else {
    Write-Host "  Bruker eksisterende .venv"
}

Trinn "Avhengigheter"
if (-not $SkipPackageUpgrade) {
    & $script:VenvPython -m pip install --upgrade pip --quiet
}
& $script:VenvPython -m pip install --quiet `
    -r (Join-Path $script:ServersRoot "xsale\requirements.txt") `
    -r (Join-Path $script:ServersRoot "mysql\requirements.txt") `
    notebooklm-mcp-cli
if ($LASTEXITCODE -ne 0) { throw "pip install feilet." }
Write-Host "  Ferdig"

# --- Mapper -----------------------------------------------------------------
Trinn "Mapper"
foreach ($d in @("secrets", "logs", "generated")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $script:KitRoot $d) | Out-Null
}
Write-Host "  secrets\ logs\ generated\"

# --- config.env -------------------------------------------------------------
Trinn "Konfigurasjon"
$configPath = Join-Path $script:KitRoot "config.env"
if (-not (Test-Path -LiteralPath $configPath)) {
    Copy-Item -LiteralPath (Join-Path $script:KitRoot "config.env.example") -Destination $configPath
    Write-Host "  Opprettet config.env fra config.env.example"
} else {
    Write-Host "  config.env finnes alt og beholdes"
}
Import-ConfigEnv

# Stier settes her, aldri i den delte eksempelfila.
function Sett-Config([string] $nokkel, [string] $verdi) {
    $linjer = @(Get-Content -LiteralPath $configPath)
    $funnet = $false
    for ($i = 0; $i -lt $linjer.Count; $i++) {
        if ($linjer[$i] -match "^\s*$([regex]::Escape($nokkel))\s*=") {
            $linjer[$i] = "$nokkel=$verdi"; $funnet = $true; break
        }
    }
    if (-not $funnet) { $linjer += "$nokkel=$verdi" }
    Set-Content -LiteralPath $configPath -Value $linjer -Encoding utf8
    [Environment]::SetEnvironmentVariable($nokkel, $verdi, "Process")
}

if (-not $AutoXsaleDir) {
    $AutoXsaleDir = if ($env:AUTO_XSALE_DIR) { $env:AUTO_XSALE_DIR } else { Get-AutoXsaleDir }
}
# Saksmappen ma ligge utenfor repoet. Ellers kan kundedata havne i Git.
$kitFull = (Resolve-Path -LiteralPath $script:KitRoot).Path
if (Test-PathInside -Child $AutoXsaleDir -Parent $kitFull) {
    throw ("AUTO_XSALE_DIR ligger inne i repoet:`n  $AutoXsaleDir`n" +
        "Saksmapper med kundedata skal ligge utenfor. Velg en annen mappe, " +
        "for eksempel $(Join-Path $env:USERPROFILE 'Documents\Auto-XSALE').")
}
New-Item -ItemType Directory -Force -Path $AutoXsaleDir | Out-Null
Sett-Config "AUTO_XSALE_DIR" $AutoXsaleDir
Write-Host "  Saksmapper: $AutoXsaleDir"

if (-not $ProjectRoot) { $ProjectRoot = Get-ProjectRoot }
New-Item -ItemType Directory -Force -Path $ProjectRoot | Out-Null
Sett-Config "PROJECT_ROOT" $ProjectRoot
Write-Host "  Prosjektrot: $ProjectRoot"

if ([string]::IsNullOrWhiteSpace($env:TASK_LEDGER)) {
    Sett-Config "TASK_LEDGER" (Join-Path $AutoXsaleDir "task.md")
}

# --- mcp.json ---------------------------------------------------------------
Trinn "MCP-konfigurasjon"
$mcpTemplate = Get-Content -Raw -LiteralPath (Join-Path $script:KitRoot "templates\mcp.json.template")
$mcpJson = $mcpTemplate.Replace("__KIT_ROOT__", $script:KitRoot.Replace("\", "\\"))
$generatedMcp = Join-Path $script:KitRoot "generated\mcp.json"
Set-Content -LiteralPath $generatedMcp -Value $mcpJson -Encoding utf8
Write-Host "  Generert: generated\mcp.json"

# Kontroller at hver -File-sti i den genererte konfigurasjonen finnes. En
# feilstavet sti gir ellers en MCP-server som bare aldri starter.
$konf = Get-Content -Raw -LiteralPath $generatedMcp | ConvertFrom-Json
foreach ($navn in $konf.mcpServers.PSObject.Properties.Name) {
    $argv = $konf.mcpServers.$navn.args
    for ($i = 0; $i -lt $argv.Count; $i++) {
        if ($argv[$i] -eq "-File" -and $i + 1 -lt $argv.Count) {
            if (-not (Test-Path -LiteralPath $argv[$i + 1])) {
                throw "MCP-server '$navn' peker pa en fil som ikke finnes: $($argv[$i+1])"
            }
        }
    }
}
Write-Host "  Alle tre serverstier kontrollert"

$projectMcp = Join-Path $ProjectRoot ".mcp.json"
if (-not (Test-Path -LiteralPath $projectMcp)) {
    Copy-Item -LiteralPath $generatedMcp -Destination $projectMcp
    Write-Host "  Opprettet $projectMcp"
} else {
    Write-Warning "  $projectMcp finnes alt og ble ikke overskrevet."
    Write-Warning "  Flett inn serverne fra generated\mcp.json manuelt."
}

# --- CLAUDE.md --------------------------------------------------------------
Trinn "Arbeidsinstruksjoner"
$projectClaude = Join-Path $ProjectRoot "CLAUDE.md"
if (-not (Test-Path -LiteralPath $projectClaude)) {
    # Fornavnet er ikke oppgitt enna - oppsett.ps1 sporr om det etterpa og
    # skriver denne fila om da. Windows-brukernavnet er bare et midlertidig
    # utgangspunkt.
    $navn = if ($env:USER_NAME) { $env:USER_NAME } else { $env:USERNAME }
    $notebook = if ($env:NOTEBOOK_NAME) { $env:NOTEBOOK_NAME } else { "Amendo Knowledge base" }

    Write-ClaudeMd -Destinasjon $projectClaude -Navn $navn -Notebook $notebook `
        -AutoXsaleDir $AutoXsaleDir
    Write-Host "  Opprettet $projectClaude (foreløpig navn: $navn)"
} else {
    Write-Host "  CLAUDE.md finnes alt og beholdes"
}

# --- Ferdig -----------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host "  Installasjonen er ferdig." -ForegroundColor Green
Write-Host ("=" * 70) -ForegroundColor Green
Write-Host ""
Write-Host "Neste steg, i denne rekkefolgen:" -ForegroundColor Cyan
Write-Host "  1. .\scripts\oppsett.ps1                 legg inn din legitimasjon"
Write-Host "  2. .\scripts\login-claude-cli.ps1        logg inn i Claude Code"
Write-Host "  3. .\scripts\configure-claude-token.ps1  lagre tokenet"
Write-Host "  4. .\scripts\login-notebooklm.ps1        nar du har fatt invitasjonen"
Write-Host "  5. .\scripts\verify.ps1                  kontroller at alt virker"
Write-Host ""
Write-Host "Apne deretter $ProjectRoot i Claude Code." -ForegroundColor Gray
Write-Host ""
