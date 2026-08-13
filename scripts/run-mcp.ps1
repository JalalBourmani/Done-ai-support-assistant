# =============================================================================
#  Starter en MCP-server med legitimasjon hentet fra DPAPI.
# =============================================================================
#  Kalles av generated\mcp.json, ikke direkte av deg. Legitimasjonen settes som
#  miljovariabler i denne prosessen og arves av serveren - den star aldri i en
#  konfigurasjonsfil og aldri pa kommandolinjen.
# =============================================================================

param(
    [Parameter(Mandatory)]
    [ValidateSet("xsale", "mysql", "notebooklm")]
    [string] $Server
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")
Import-ConfigEnv
Assert-KitLayout

switch ($Server) {
    "xsale" {
        # Serveren har historisk hatt en innebygd standard-URL som pekte pa en
        # ANNEN organisasjon. Er XSALE_URL ikke satt, skal det feile her - ikke
        # logge inn et helt annet sted uten a si det.
        if ([string]::IsNullOrWhiteSpace($env:XSALE_URL)) {
            throw ("XSALE_URL er ikke satt i config.env. Serveren ma ikke falle tilbake pa " +
                "en innebygd standardverdi - den kan peke pa en annen organisasjon.")
        }
        Import-EncryptedCredential `
            -Path (Join-Path $script:KitRoot "secrets\xsale.xml") `
            -UsernameVariable "XSALE_EMAIL" `
            -PasswordVariable "XSALE_PASSWORD"
        & $script:VenvPython (Join-Path $script:ServersRoot "xsale\mcp_server.py")
        exit $LASTEXITCODE
    }

    "mysql" {
        if ([string]::IsNullOrWhiteSpace($env:PMA_URL)) {
            throw "PMA_URL er ikke satt i config.env."
        }
        Import-EncryptedCredential `
            -Path (Join-Path $script:KitRoot "secrets\mysql.xml") `
            -UsernameVariable "DB_USER" `
            -PasswordVariable "DB_PASSWORD"
        & $script:VenvPython (Join-Path $script:ServersRoot "mysql\mcp_server.py")
        exit $LASTEXITCODE
    }

    "notebooklm" {
        $exe = Join-Path $script:VenvRoot "Scripts\notebooklm-mcp.exe"
        if (-not (Test-Path -LiteralPath $exe)) {
            throw "NotebookLM MCP er ikke installert. Kjor scripts\install.ps1."
        }
        # Innloggingen ligger i brukerens egen profil under
        # %USERPROFILE%\.notebooklm-mcp-cli\, ikke i settet. Den skal aldri
        # kopieres mellom maskiner - den inneholder aktive Google-sesjonsinfokapsler.
        & $exe
        exit $LASTEXITCODE
    }
}
