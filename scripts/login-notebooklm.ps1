<#
.SYNOPSIS
    Logger inn mot NotebookLM med din egen Google-konto.

.DESCRIPTION
    Apner en nettleser der du logger inn. Innloggingen lagres i din egen
    brukerprofil under %USERPROFILE%\.notebooklm-mcp-cli\, ikke i settet.

    Den mappen inneholder aktive Google-sesjonsinfokapsler i klartekst. Den skal
    aldri kopieres til en annen maskin, legges i Git eller tas med i en
    sikkerhetskopi som deles.

    Du ma vaere invitert til det delte prosjektet for dette virker. Har du ikke
    fatt invitasjonen, kjor .\scripts\oppsett.ps1 -Bare notebooklm og send
    meldingen den lager.
#>
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
Import-ConfigEnv -Valgfri

$nlm = Join-Path $script:VenvRoot "Scripts\nlm.exe"
if (-not (Test-Path -LiteralPath $nlm)) {
    throw "NotebookLM CLI er ikke installert. Kjor scripts\install.ps1 forst."
}

$notebook = if ($env:NOTEBOOK_NAME) { $env:NOTEBOOK_NAME } else { "Amendo Knowledge base" }
$konto = $env:NOTEBOOKLM_ACCOUNT

Write-Host ""
Write-Host "NotebookLM-innlogging" -ForegroundColor Cyan
Write-Host "Prosjekt: $notebook" -ForegroundColor Gray
if ($konto) {
    Write-Host "Logg inn med: $konto" -ForegroundColor Gray
} else {
    Write-Host "Logg inn med Google-kontoen du bruker pa jobb." -ForegroundColor Gray
}
Write-Host ""
Write-Host "Har du ikke fatt invitasjonen enna, avbryt med Ctrl+C og be om den forst." -ForegroundColor DarkYellow
Write-Host ""

& $nlm login
if ($LASTEXITCODE -ne 0) {
    throw "Innloggingen feilet (kode $LASTEXITCODE)."
}

Write-Host ""
Write-Host "Innlogget. Kontroller at prosjektet er synlig:" -ForegroundColor Green
Write-Host "  .\scripts\verify.ps1" -ForegroundColor Gray
Write-Host ""
