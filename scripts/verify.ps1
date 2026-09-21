# =============================================================================
#  Done.ai Support Assistant — kontroll
# =============================================================================
#  Kjor denne nar noe ikke virker, og ta med utdataen nar du ber om hjelp.
#
#  Prinsipp: ingenting godkjennes pa at en fil finnes. Python kjores, servere
#  startes, legitimasjon dekrypteres. En gronn linje her skal bety at det
#  faktisk virker.
# =============================================================================

param(
    # Hopp over de tre server-oppstartene. De tar 30-60 sekunder hver.
    [switch] $Rask
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")

$script:Feil = 0
$script:Advarsler = 0

function Sjekk([string] $navn, [scriptblock] $test) {
    Write-Host ("  {0,-38} " -f $navn) -NoNewline
    try {
        $r = & $test
        if ($r -is [string] -and $r.StartsWith("ADVARSEL")) {
            Write-Host "ADVARSEL" -ForegroundColor Yellow
            Write-Host ("      " + $r.Substring(8).Trim()) -ForegroundColor DarkYellow
            $script:Advarsler++
            return
        }
        Write-Host "OK" -ForegroundColor Green
        if ($r -is [string] -and $r) { Write-Host ("      " + $r) -ForegroundColor DarkGray }
    }
    catch {
        Write-Host "FEIL" -ForegroundColor Red
        Write-Host ("      " + $_.Exception.Message) -ForegroundColor Yellow
        $script:Feil++
    }
}

function Overskrift([string] $t) {
    Write-Host ""
    Write-Host $t -ForegroundColor Cyan
    Write-Host ("-" * 60) -ForegroundColor DarkCyan
}

Write-Host ""
Write-Host "Done.ai Support Assistant - kontroll" -ForegroundColor White
Write-Host "Sett: $($script:KitRoot)" -ForegroundColor DarkGray

# --- Settet -----------------------------------------------------------------
Overskrift "Settet"
Sjekk "Filstruktur" { Assert-KitLayout; "servers\xsale og servers\mysql funnet" }
Sjekk "config.env" {
    Import-ConfigEnv
    $mangler = @()
    foreach ($n in @("XSALE_URL", "PMA_URL", "CONFLUENCE_URL", "AUTO_XSALE_DIR")) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($n))) { $mangler += $n }
    }
    if ($mangler) { throw "Mangler verdier: $($mangler -join ', '). Kjor install.ps1 og oppsett.ps1." }
    "XSALE_URL=$env:XSALE_URL"
}
Sjekk "Tegnkoding i skriptene" {
    # Windows PowerShell 5.1 leser en .ps1 uten UTF-8 BOM som Windows-1252, og da
    # blir norske tegn mojibake i alt utdata. Fanges her fordi det ellers bare
    # ser ut som en skrivefeil.
    $uten = @()
    foreach ($p in (Get-ChildItem -LiteralPath (Join-Path $script:KitRoot "scripts") -Filter *.ps1)) {
        $bytes = [IO.File]::ReadAllBytes($p.FullName)
        $harBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
        if (-not $harBom) { $uten += $p.Name }
    }
    if ($uten.Count -gt 0) {
        return ("ADVARSEL Disse mangler UTF-8 BOM og vil vise norske tegn feil: " + ($uten -join ", "))
    }
    "alle .ps1 har UTF-8 BOM"
}
Sjekk "Saksmappe utenfor repoet" {
    $d = Get-AutoXsaleDir
    if (-not (Test-Path -LiteralPath $d)) { throw "Finnes ikke: $d" }
    $kit = (Resolve-Path -LiteralPath $script:KitRoot).Path
    if (Test-PathInside -Child (Resolve-Path -LiteralPath $d).Path -Parent $kit) {
        throw "Saksmappen ligger INNE i repoet: $d. Kundedata kan havne i Git."
    }
    $d
}

# --- Python -----------------------------------------------------------------
Overskrift "Python"
Sjekk "Virtuelt miljo kjorer" {
    if (-not (Test-Path -LiteralPath $script:VenvPython)) { throw "Mangler .venv. Kjor install.ps1." }
    $v = (& $script:VenvPython --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Interpreteren starter ikke: $v" }
    if ($v -match "(\d+)\.(\d+)") {
        if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 10)) {
            throw "$v er for gammel. Kreves 3.10 eller nyere."
        }
    }
    $v
}
Sjekk "Pakker installert" {
    $ut = (& $script:VenvPython -c "import mcp, requests; print('mcp+requests ok')" 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Import feilet: $ut" }
    $ut
}

# --- Legitimasjon -----------------------------------------------------------
Overskrift "Legitimasjon"
function Sjekk-Cred([string] $visning, [string] $fil, [string] $rettelse) {
    Sjekk $visning {
        $sti = Join-Path $script:KitRoot "secrets\$fil"
        if (-not (Test-Path -LiteralPath $sti)) { throw "Ikke satt opp enna. $rettelse" }
        $lengde = (Get-Item -LiteralPath $sti).Length
        try { $c = Import-Clixml -LiteralPath $sti }
        catch {
            throw ("Kan ikke dekrypteres. Fila er laget av en annen Windows-bruker " +
                "eller pa en annen maskin. $rettelse")
        }
        if (-not $c.UserName) {
            throw "Fila er tom ($lengde bytes) - dialogen ble sannsynligvis avbrutt. $rettelse"
        }
        "bruker $($c.UserName)"
    }
}
Sjekk-Cred "XSALE" "xsale.xml" "Kjor: .\scripts\oppsett.ps1 -Bare xsale"
Sjekk-Cred "MySQL" "mysql.xml" "Kjor: .\scripts\oppsett.ps1 -Bare mysql"
Sjekk-Cred "Claude-token" "claude-token.xml" "Kjor: .\scripts\configure-claude-token.ps1"

# --- Claude Code ------------------------------------------------------------
Overskrift "Claude Code"
Sjekk "CLI funnet" { Resolve-ClaudeCli }
Sjekk "Autentisert" {
    $exe = Resolve-ClaudeCli
    $s = (& $exe auth status 2>&1 | Out-String).Trim()
    if ($s -match '"loggedIn"\s*:\s*true') { return "innlogget" }
    if (Test-Path -LiteralPath (Join-Path $script:KitRoot "secrets\claude-token.xml")) {
        return "ADVARSEL auth status melder ikke loggedIn, men et lagret token finnes. Uovervakede kjoringer bruker tokenet."
    }
    throw "Ikke innlogget. Kjor .\scripts\login-claude-cli.ps1"
}
Sjekk "generated\mcp.json" {
    $p = Join-Path $script:KitRoot "generated\mcp.json"
    if (-not (Test-Path -LiteralPath $p)) { throw "Mangler. Kjor install.ps1." }
    $k = Get-Content -Raw -LiteralPath $p | ConvertFrom-Json
    $navn = @($k.mcpServers.PSObject.Properties.Name)
    foreach ($n in $navn) {
        $argv = $k.mcpServers.$n.args
        for ($i = 0; $i -lt $argv.Count; $i++) {
            if ($argv[$i] -eq "-File" -and -not (Test-Path -LiteralPath $argv[$i + 1])) {
                throw "Server '$n' peker pa en fil som ikke finnes: $($argv[$i+1])"
            }
        }
    }
    "$($navn.Count) servere: $($navn -join ', ')"
}
Sjekk ".mcp.json i prosjektroten" {
    $root = Get-ProjectRoot
    $p = Join-Path $root ".mcp.json"
    if (-not (Test-Path -LiteralPath $p)) {
        throw "Mangler $p. Claude Code laster MCP-servere fra prosjektroten - apne $root, ikke en annen mappe."
    }
    $p
}

# --- MCP-servere ------------------------------------------------------------
Overskrift "MCP-servere (starter dem faktisk)"
if ($Rask) {
    Write-Host "  Hoppet over (-Rask). Kjor uten flagget for full kontroll." -ForegroundColor DarkYellow
} else {
    $smoke = Join-Path $PSScriptRoot "mcp_smoketest.py"
    $servere = @(
        @{ navn = "xsale-crm";          arg = "xsale";      verktoy = "list_my_cases" },
        @{ navn = "mysql-query-server"; arg = "mysql";      verktoy = "execute_query" },
        @{ navn = "kunnskap";           arg = "kunnskap";   verktoy = "kunnskapsstatus" }
    )
    foreach ($s in $servere) {
        Sjekk $s.navn {
            $a = @($smoke, $s.arg)
            if ($s.verktoy) { $a += @("--tool", $s.verktoy) }
            $ut = (& $script:VenvPython @a 2>&1 | Out-String).Trim()
            if ($ut -like "OK*") { return $ut.Substring(2).Trim() }
            if ($s.arg -eq "kunnskap") {
                # Hjelpesenteret paa support.amendo.no er offentlig, saa
                # serveren virker halvveis uten Confluence-token. Da er det en
                # advarsel, ikke en feil.
                return "ADVARSEL $ut`n      Mangler Confluence-token? Kjor .\scripts\oppsett.ps1 -Bare confluence"
            }
            throw $ut
        }
    }
}

# --- Oppsummering -----------------------------------------------------------
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor DarkCyan
if ($script:Feil -eq 0 -and $script:Advarsler -eq 0) {
    Write-Host "  Alt bestatt. Du er klar." -ForegroundColor Green
} elseif ($script:Feil -eq 0) {
    Write-Host "  Bestatt med $($script:Advarsler) advarsel(er)." -ForegroundColor Yellow
    Write-Host "  Advarsler stopper deg ikke, men les dem." -ForegroundColor DarkYellow
} else {
    Write-Host "  $($script:Feil) feil og $($script:Advarsler) advarsel(er)." -ForegroundColor Red
    Write-Host "  Rett feilene ovenfra og ned - de henger ofte sammen." -ForegroundColor DarkYellow
}
Write-Host ("=" * 60) -ForegroundColor DarkCyan
Write-Host ""
exit $(if ($script:Feil -gt 0) { 1 } else { 0 })
