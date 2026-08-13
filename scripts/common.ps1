# =============================================================================
#  Delt bibliotek. Dot-sources av alle andre skript.
# =============================================================================
$ErrorActionPreference = "Stop"

# KitRoot utledes fra hvor dette skriptet ligger, aldri fra konfigurasjon. Da
# virker settet uansett hvor det klones, og det finnes bare en sannhet.
$script:KitRoot = Split-Path -Parent $PSScriptRoot
$script:VenvRoot = Join-Path $script:KitRoot ".venv"
$script:ServersRoot = Join-Path $script:KitRoot "servers"

# Windows-oppsett. Sett eksplisitt, ikke antatt: pa POSIX heter det bin/python,
# og da skal det feile tydelig framfor a lete etter en fil som ikke finnes.
$script:VenvPython = Join-Path $script:VenvRoot "Scripts\python.exe"

function Assert-KitLayout {
    <#
        Serverne ligger inne i repoet (servers\xsale, servers\mysql). Den gamle
        versjonen antok i stedet at de la som soskenmapper ETT niva over settet,
        og pekte dermed rett ut i tomme luften hvis settet ble klonet et annet
        sted. Sjekk kontrakten framfor a anta den.
    #>
    $mangler = @()
    foreach ($s in @("xsale", "mysql")) {
        $fil = Join-Path $script:ServersRoot "$s\mcp_server.py"
        if (-not (Test-Path -LiteralPath $fil)) { $mangler += $fil }
    }
    if ($mangler.Count -gt 0) {
        throw ("Settet er ufullstendig. Fant ikke:`n  " + ($mangler -join "`n  ") +
            "`nHentet du repoet med 'git clone'? Kjor deretter scripts\install.ps1.")
    }
}

function Import-ConfigEnv {
    param([switch] $Valgfri)

    $configPath = Join-Path $script:KitRoot "config.env"
    if (-not (Test-Path -LiteralPath $configPath)) {
        if ($Valgfri) { return }
        throw "Mangler $configPath. Kjor scripts\install.ps1 forst."
    }

    foreach ($line in Get-Content -LiteralPath $configPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) { continue }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
    }
}

function Get-AutoXsaleDir {
    <# Saksmappen med kundedata. Ligger UTENFOR repoet med vilje. #>
    $dir = $env:AUTO_XSALE_DIR
    if ([string]::IsNullOrWhiteSpace($dir)) {
        $dir = Join-Path $env:USERPROFILE "Documents\Auto-XSALE"
    }
    return $dir
}

function Get-ProjectRoot {
    <# Mappen brukeren apner i Claude Code. Her legges .mcp.json og CLAUDE.md. #>
    $root = $env:PROJECT_ROOT
    if ([string]::IsNullOrWhiteSpace($root)) { $root = $script:KitRoot }
    return $root
}

function Test-PathInside {
    <#
        Ligger $Child inne i $Parent?

        En ren StartsWith-sammenligning respekterer ikke mappegrenser:
        "C:\Temp\kit-test-saker" starter med "C:\Temp\kit-test", men ligger ikke
        inni den. Skilletegnet ma vaere med i sammenligningen.
    #>
    param(
        [Parameter(Mandatory)] [string] $Child,
        [Parameter(Mandatory)] [string] $Parent
    )
    $sep = [IO.Path]::DirectorySeparatorChar
    $c = $Child.TrimEnd($sep, [IO.Path]::AltDirectorySeparatorChar) + $sep
    $p = $Parent.TrimEnd($sep, [IO.Path]::AltDirectorySeparatorChar) + $sep
    return $c.StartsWith($p, [StringComparison]::OrdinalIgnoreCase)
}

function Write-ClaudeMd {
    <#
        Genererer CLAUDE.md fra malen med brukerens egne verdier.

        Ligger her fordi to skript trenger den: install.ps1 lager fila forst, og
        oppsett.ps1 skriver den om nar fornavnet er kjent. Uten det siste ville
        fila blitt staende med Windows-brukernavnet, siden install kjorer for
        brukeren har oppgitt noe navn.
    #>
    param(
        [Parameter(Mandatory)] [string] $Destinasjon,
        [Parameter(Mandatory)] [string] $Navn,
        [Parameter(Mandatory)] [string] $Notebook,
        [Parameter(Mandatory)] [string] $AutoXsaleDir
    )

    $malPath = Join-Path $script:KitRoot "templates\CLAUDE.md.template"
    $mal = Get-Content -Raw -LiteralPath $malPath
    $mal = $mal.
        Replace("__USER_NAME__", $Navn).
        Replace("__NOTEBOOK_NAME__", $Notebook).
        Replace("__AUTO_XSALE_DIR__", $AutoXsaleDir)

    # En glemt plassholder skal stoppe her, ikke havne i teksten modellen leser
    # som instruks.
    $rest = [regex]::Matches($mal, '__[A-Z_]+__') | ForEach-Object { $_.Value } | Sort-Object -Unique
    if ($rest) { throw "CLAUDE.md-malen har uerstattede plassholdere: $($rest -join ', ')" }

    Set-Content -LiteralPath $Destinasjon -Value $mal -Encoding utf8
}

function Resolve-ClaudeCli {
    <#
        Finner Claude Code CLI. Desktop-appen legger ikke 'claude' i PATH, men
        leverer binaeren i en versjonsnummerert mappe. Appen er MSIX-pakket, og
        det gir to ulike stier til samme fil:

          Reell:        %LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\<ver>
          Virtualisert: %APPDATA%\Claude\claude-code\<ver>

        Den virtualiserte stien er BARE synlig for prosesser som arver appens
        pakkecontainer. Oppgaveplanlegging og vanlige PowerShell-vinduer ser den
        ikke. Derfor prioriteres den reelle stien.

        CLAUDE_CLI_PATH i config.env overstyrer alt, for installasjoner vi ikke
        har forutsett.
    #>
    if ($env:CLAUDE_CLI_PATH -and (Test-Path -LiteralPath $env:CLAUDE_CLI_PATH)) {
        return $env:CLAUDE_CLI_PATH
    }

    # -CommandType Application: uten den treffer Get-Command ogsa aliaser og
    # funksjoner fra brukerens profil, og .Source blir tom - da returnerte den
    # gamle versjonen en tom streng i stedet for a feile tydelig.
    $cmd = Get-Command claude -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($cmd -and $cmd.Source -and (Test-Path -LiteralPath $cmd.Source)) {
        return $cmd.Source
    }

    $roots = @()
    Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude*" -ErrorAction SilentlyContinue |
        ForEach-Object {
            $roots += (Join-Path $_.FullName "LocalCache\Roaming\Claude\claude-code")
        }
    $roots += (Join-Path $env:APPDATA "Claude\claude-code")
    # Frittstaende installasjon via 'claude install'.
    $roots += (Join-Path $env:USERPROFILE ".local\bin")
    $roots += (Join-Path $env:LOCALAPPDATA "Programs\claude-code")

    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }

        # Binaeren kan ligge direkte i mappen, eller i versjonsnummererte undermapper.
        $direkte = Join-Path $root "claude.exe"
        if (Test-Path -LiteralPath $direkte) { return $direkte }

        $candidates = Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "claude.exe") }
        $sorted = @($candidates | Sort-Object -Property @{ Expression = {
            try { [version]$_.Name } catch { [version]"0.0.0" }
        } } -Descending)

        if ($sorted.Count -gt 0) {
            return (Join-Path $sorted[0].FullName "claude.exe")
        }
    }

    throw ("Fant ikke Claude Code CLI. Sokte i PATH og under:`n  " + ($roots -join "`n  ") +
        "`nTips: 'claude install' gir en frittstaende CLI i PATH, uavhengig av MSIX-pakken." +
        "`nAlternativt: sett CLAUDE_CLI_PATH i config.env til full sti til claude.exe.")
}

function Import-EncryptedCredential {
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $UsernameVariable,
        [Parameter(Mandatory)] [string] $PasswordVariable
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Mangler kryptert legitimasjon: $Path. Kjor scripts\oppsett.ps1."
    }

    # DPAPI binder krypteringen til Windows-bruker OG maskin. Kopierte filer
    # feiler her, og den gamle versjonen ga da en ubrukelig systemfeil i stedet
    # for a si hva som var galt.
    try {
        $credential = Import-Clixml -LiteralPath $Path
    }
    catch {
        throw ("Klarte ikke dekryptere $Path.`n" +
            "Fila er kryptert for en annen Windows-bruker eller en annen maskin. " +
            "Legitimasjon kan ikke kopieres mellom maskiner.`n" +
            "Kjor scripts\oppsett.ps1 pa nytt pa denne maskinen.`n" +
            "Underliggende feil: " + $_.Exception.Message)
    }

    if (-not $credential.UserName) {
        throw ("$Path er tom. Det skjer nar en passorddialog blir avbrutt.`n" +
            "Kjor scripts\oppsett.ps1 pa nytt.")
    }

    [Environment]::SetEnvironmentVariable($UsernameVariable, $credential.UserName, "Process")
    [Environment]::SetEnvironmentVariable(
        $PasswordVariable,
        $credential.GetNetworkCredential().Password,
        "Process"
    )
}
