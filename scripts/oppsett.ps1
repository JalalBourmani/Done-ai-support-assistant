# =============================================================================
#  Done.ai Support Assistant — interaktivt oppsett
# =============================================================================
#  Kjores etter install.ps1. Sporr om alt som er personlig, lagrer det kryptert,
#  og TESTER hver innlogging med en gang. Trygg a kjore om igjen.
#
#  Bevisste valg:
#   - Konsoll, ikke GUI-dialog. Get-Credential-dialogen kan avbrytes, og
#     etterlater da en tom credential-fil som ser gyldig ut. Read-Host kan ikke
#     avbrytes pa samme mate.
#   - Hver legitimasjon valideres mot tjenesten for vi gar videre, slik at feil
#     passord oppdages her og ikke midt i en saksbehandling.
#   - Ingenting skrives i klartekst. Passord gar rett fra SecureString til DPAPI.
# =============================================================================

param(
    # Hopp over deler du alt har satt opp: -Bare xsale,mysql,navn,notebooklm
    [string[]] $Bare
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

function Skal-Kjore([string] $del) {
    if (-not $Bare -or $Bare.Count -eq 0) { return $true }
    return $Bare -contains $del
}

function Skriv-Tittel([string] $t) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor DarkCyan
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor DarkCyan
}

function Les-Tekst([string] $ledetekst, [string] $standard = "") {
    while ($true) {
        $vist = if ($standard) { "$ledetekst [$standard]" } else { $ledetekst }
        $svar = Read-Host $vist
        if ([string]::IsNullOrWhiteSpace($svar) -and $standard) { return $standard }
        if (-not [string]::IsNullOrWhiteSpace($svar)) { return $svar.Trim() }
        Write-Host "  Ma fylles ut." -ForegroundColor Yellow
    }
}

function Les-Passord([string] $ledetekst) {
    while ($true) {
        $s = Read-Host $ledetekst -AsSecureString
        if ($s.Length -gt 0) { return $s }
        Write-Host "  Passordet kan ikke vaere tomt." -ForegroundColor Yellow
    }
}

function Lagre-Legitimasjon([string] $fil, [string] $bruker, [System.Security.SecureString] $passord) {
    $sti = Join-Path $script:KitRoot "secrets\$fil"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $sti) | Out-Null
    $cred = New-Object System.Management.Automation.PSCredential($bruker, $passord)
    $cred | Export-Clixml -Path $sti
    # Kontroller at fila faktisk kan leses tilbake. En tom eller ulesbar fil skal
    # ikke passere som konfigurert.
    $tilbake = Import-Clixml -Path $sti
    if (-not $tilbake.UserName) { throw "Klarte ikke lese tilbake $fil etter lagring." }
    Write-Host "  Lagret kryptert: secrets\$fil  (bruker $($tilbake.UserName), passord $($passord.Length) tegn)" -ForegroundColor DarkGray
}

function Sett-Config([string] $nokkel, [string] $verdi) {
    $sti = Join-Path $script:KitRoot "config.env"
    if (-not (Test-Path -LiteralPath $sti)) {
        Copy-Item (Join-Path $script:KitRoot "config.env.example") $sti
    }
    $linjer = @(Get-Content -LiteralPath $sti)
    $funnet = $false
    for ($i = 0; $i -lt $linjer.Count; $i++) {
        if ($linjer[$i] -match "^\s*$([regex]::Escape($nokkel))\s*=") {
            $linjer[$i] = "$nokkel=$verdi"
            $funnet = $true
            break
        }
    }
    if (-not $funnet) { $linjer += "$nokkel=$verdi" }
    Set-Content -LiteralPath $sti -Value $linjer -Encoding utf8
}

# Kjorer en kort Python-test i venv-et. Legitimasjonen sendes via miljovariabler
# i barneprosessen, aldri via kommandolinjen (der den ville vaert synlig i
# prosesslista).
function Test-Innlogging([string] $tjeneste, [hashtable] $miljo, [string] $pythonKode) {
    $gamle = @{}
    foreach ($k in $miljo.Keys) {
        $gamle[$k] = [Environment]::GetEnvironmentVariable($k)
        [Environment]::SetEnvironmentVariable($k, $miljo[$k])
    }
    try {
        $tmp = [IO.Path]::GetTempFileName() + ".py"
        Set-Content -LiteralPath $tmp -Value $pythonKode -Encoding utf8
        Write-Host "  Tester innlogging mot $tjeneste ..." -NoNewline
        $ut = (& $script:VenvPython $tmp | Out-String).Trim()
        if ($ut -like "OK*") {
            Write-Host " bekreftet" -ForegroundColor Green
            if ($ut.Length -gt 2) { Write-Host "    $($ut.Substring(2).Trim())" -ForegroundColor DarkGray }
            return $true
        }
        Write-Host " FEILET" -ForegroundColor Red
        Write-Host "    $ut" -ForegroundColor Yellow
        return $false
    }
    finally {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
        foreach ($k in $gamle.Keys) { [Environment]::SetEnvironmentVariable($k, $gamle[$k]) }
    }
}

# --- Forutsetninger ---------------------------------------------------------
if (-not (Test-Path -LiteralPath $script:VenvPython)) {
    throw "Fant ikke $($script:VenvPython). Kjor scripts\install.ps1 forst."
}
Import-ConfigEnv

Skriv-Tittel "Done.ai Support Assistant - oppsett"
Write-Host @"
Du blir bedt om fire ting:

  1. Fornavnet ditt              - slik assistenten kan tiltale deg
  2. XSALE-innlogging            - din egen, ikke noen andres
  3. MySQL-innlogging            - din egen bruker pa ws.tellix.no
  4. Google-adressen din         - for invitasjon til NotebookLM-prosjektet

Passordene vises ikke nar du skriver dem, og lagres kryptert med Windows DPAPI.
De kan ikke leses av andre brukere eller pa andre maskiner.

Ingenting av dette havner i Git.
"@ -ForegroundColor Gray

# --- 1. Fornavn -------------------------------------------------------------
if (Skal-Kjore "navn") {
    Skriv-Tittel "1 av 4 - Hva heter du?"
    Write-Host "Brukes til tiltale i arbeidsinstruksjonene. Ikke til noe annet." -ForegroundColor Gray
    $fornavn = Les-Tekst "Fornavn" $env:USERNAME
    Sett-Config "USER_NAME" $fornavn
    Write-Host "  Hei, $fornavn." -ForegroundColor Green

    # install.ps1 skrev CLAUDE.md for navnet var kjent, og hopper over fila hvis
    # den finnes. Uten denne omskrivingen ville navnet du oppgir her aldri blitt
    # brukt - fila ville statt med Windows-brukernavnet.
    $projectClaude = Join-Path (Get-ProjectRoot) "CLAUDE.md"
    if (Test-Path -LiteralPath $projectClaude) {
        try {
            Write-ClaudeMd `
                -Destinasjon $projectClaude `
                -Navn $fornavn `
                -Notebook $(if ($env:NOTEBOOK_NAME) { $env:NOTEBOOK_NAME } else { "Amendo Knowledge base" }) `
                -AutoXsaleDir (Get-AutoXsaleDir)
            Write-Host "  Oppdaterte CLAUDE.md med navnet ditt." -ForegroundColor DarkGray
        }
        catch {
            Write-Warning "  Klarte ikke oppdatere CLAUDE.md: $($_.Exception.Message)"
        }
    }
}

# --- 2. XSALE ---------------------------------------------------------------
if (Skal-Kjore "xsale") {
    Skriv-Tittel "2 av 4 - XSALE"
    $xsaleUrl = if ($env:XSALE_URL) { $env:XSALE_URL } else { "https://plorea.new.xsale.no" }
    Write-Host "Logger inn mot: $xsaleUrl" -ForegroundColor Gray
    Write-Host "Er det feil installasjon, avbryt og rett XSALE_URL i config.env." -ForegroundColor DarkGray

    $ok = $false
    for ($forsok = 1; $forsok -le 3 -and -not $ok; $forsok++) {
        $epost = Les-Tekst "XSALE e-post"
        $passord = Les-Passord "XSALE passord"
        $klar = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($passord))
        $ok = Test-Innlogging "XSALE" @{
            XSALE_URL = $xsaleUrl; XSALE_EMAIL = $epost; XSALE_PASSWORD = $klar
        } @"
import os, sys
sys.path.insert(0, r'$(Join-Path $script:KitRoot "servers\xsale")')
try:
    import mcp_server as X
    X._get_session()
    who = X.get_logged_user()
    print('OK ' + str(who)[:160])
except Exception as e:
    print('FEIL: ' + str(e)[:300])
"@
        $klar = $null
        if (-not $ok -and $forsok -lt 3) {
            Write-Host "  Prov igjen. Sjekk e-post og passord." -ForegroundColor Yellow
        }
    }
    if ($ok) {
        Lagre-Legitimasjon "xsale.xml" $epost $passord
    } else {
        Write-Warning "XSALE ble ikke bekreftet. Ingenting lagret. Kjor: scripts\oppsett.ps1 -Bare xsale"
    }
}

# --- 3. MySQL ---------------------------------------------------------------
if (Skal-Kjore "mysql") {
    Skriv-Tittel "3 av 4 - ProTouch / MySQL"
    $pmaUrl = if ($env:PMA_URL) { $env:PMA_URL } else { "https://ws.tellix.no/phpmyadmin/" }
    Write-Host "Logger inn mot: $pmaUrl" -ForegroundColor Gray
    Write-Host "Tilgangen er skrivebeskyttet. Innlogging kan ta 30-40 sekunder." -ForegroundColor DarkGray

    $ok = $false
    for ($forsok = 1; $forsok -le 3 -and -not $ok; $forsok++) {
        $dbBruker = Les-Tekst "MySQL brukernavn"
        $dbPassord = Les-Passord "MySQL passord"
        $klar = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($dbPassord))
        $ok = Test-Innlogging "phpMyAdmin" @{
            PMA_URL = $pmaUrl; DB_USER = $dbBruker; DB_PASSWORD = $klar
            DB_NAME = $(if ($env:DB_NAME) { $env:DB_NAME } else { "protouch" })
        } @"
import os, sys
sys.path.insert(0, r'$(Join-Path $script:KitRoot "servers\mysql")')
try:
    import mcp_server as M
    out = M.execute_query('SELECT DATABASE() AS db, VERSION() AS v')
    if out.startswith(('Error', 'Authentication', 'HTTP', 'Database Error')):
        print('FEIL: ' + out[:300])
    else:
        print('OK ' + out.replace('\n', ' ')[:160])
except Exception as e:
    print('FEIL: ' + str(e)[:300])
"@
        $klar = $null
        if (-not $ok -and $forsok -lt 3) {
            Write-Host "  Prov igjen. Har du egen bruker pa ws.tellix.no?" -ForegroundColor Yellow
        }
    }
    if ($ok) {
        Lagre-Legitimasjon "mysql.xml" $dbBruker $dbPassord
    } else {
        Write-Warning "MySQL ble ikke bekreftet. Ingenting lagret. Kjor: scripts\oppsett.ps1 -Bare mysql"
    }
}

# --- 4. NotebookLM ----------------------------------------------------------
if (Skal-Kjore "notebooklm") {
    Skriv-Tittel "4 av 4 - NotebookLM"
    Write-Host @"
Kunnskapsbasen med Confluence-artiklene ligger i et delt NotebookLM-prosjekt.
Du ma inviteres for du far tilgang.
"@ -ForegroundColor Gray
    $gmail = Les-Tekst "Google-adressen du bruker pa jobb"
    Sett-Config "NOTEBOOKLM_ACCOUNT" $gmail

    $melding = Join-Path $script:KitRoot "generated\notebooklm-forespursel.txt"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $melding) | Out-Null
    $navn = if ($env:USER_NAME) { $env:USER_NAME } else { "" }
    @"
Hei Jalal,

Kan du invitere meg til NotebookLM-prosjektet "$(if ($env:NOTEBOOK_NAME) { $env:NOTEBOOK_NAME } else { 'Amendo Knowledge base' })"?

Google-konto: $gmail
Navn: $navn

Takk!
"@ | Set-Content -LiteralPath $melding -Encoding utf8

    Write-Host ""
    Write-Host "  Send denne til Jalal:" -ForegroundColor Yellow
    Write-Host "  $melding" -ForegroundColor White
    Write-Host ""
    Write-Host "  Nar du har fatt invitasjonen, kjor: scripts\login-notebooklm.ps1" -ForegroundColor Gray
}

# --- Oppsummering -----------------------------------------------------------
Skriv-Tittel "Status"
$deler = @(
    @{ navn = "Fornavn";      ok = -not [string]::IsNullOrWhiteSpace($env:USER_NAME) -or (Skal-Kjore "navn") },
    @{ navn = "XSALE";        ok = (Test-Path (Join-Path $script:KitRoot "secrets\xsale.xml")) },
    @{ navn = "MySQL";        ok = (Test-Path (Join-Path $script:KitRoot "secrets\mysql.xml")) },
    @{ navn = "Claude-token"; ok = (Test-Path (Join-Path $script:KitRoot "secrets\claude-token.xml")) }
)
foreach ($d in $deler) {
    $merke = if ($d.ok) { "OK   " } else { "MANGLER" }
    $farge = if ($d.ok) { "Green" } else { "Yellow" }
    Write-Host ("  {0,-8} {1}" -f $merke, $d.navn) -ForegroundColor $farge
}

Write-Host ""
Write-Host "Neste steg:" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $script:KitRoot "secrets\claude-token.xml"))) {
    Write-Host "  1. scripts\login-claude-cli.ps1        (logg inn i Claude Code)"
    Write-Host "  2. scripts\configure-claude-token.ps1  (lagre tokenet)"
}
Write-Host "  3. scripts\login-notebooklm.ps1        (nar du har fatt invitasjonen)"
Write-Host "  4. scripts\verify.ps1                  (kontroller at alt virker)"
Write-Host ""
