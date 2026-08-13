# Kom i gang

Regn med **20–30 minutter** første gang. Har du lest [FORUTSETNINGER.md](FORUTSETNINGER.md) og bedt om
NotebookLM-invitasjonen på forhånd, går det raskere.

Alle kommandoer kjøres fra repo-mappen i **PowerShell**.

---

## 0. Åpne PowerShell riktig

Windows blokkerer skript som er lastet ned eller kopiert fra en annen maskin. Det stopper den aller
første kommandoen, så gjør dette først:

```powershell
Get-ChildItem -Recurse . | Unblock-File
```

Får du fortsatt «kan ikke lastes fordi kjøring av skript er deaktivert», kjør enten:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

…eller start hvert skript slik i stedet:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

> Settet forutsetter **Windows PowerShell 5.1**, som følger med Windows. PowerShell 7 fungerer også,
> men er ikke testet like grundig.

---

## 1. Klon repoet

```powershell
git clone https://github.com/<konto>/Done-ai-support-assistant.git
cd Done-ai-support-assistant
```

## 2. Installer

```powershell
.\scripts\install.ps1
```

Denne bygger et Python-miljø i `.venv\`, installerer avhengighetene, oppretter `config.env`, og
genererer MCP-konfigurasjonen med stiene til **din** maskin.

Vil du styre hvor saksmappene legges:

```powershell
.\scripts\install.ps1 -AutoXsaleDir "D:\Auto-XSALE"
```

Mappen må ligge utenfor repoet. Installeren nekter hvis du peker inn i det — kundedata skal ikke kunne
havne i Git.

## 3. Legg inn din legitimasjon

```powershell
.\scripts\oppsett.ps1
```

Du blir spurt om fire ting: fornavnet ditt, XSALE-innlogging, MySQL-innlogging, og Google-adressen din.

**Hver innlogging testes med en gang.** Er passordet feil, får du beskjed der og da og tre forsøk.
Ingenting lagres før innloggingen er bekreftet.

Skal du bare rette én av dem senere:

```powershell
.\scripts\oppsett.ps1 -Bare xsale
```

## 4. Logg inn i Claude Code

To steg, i denne rekkefølgen. Begge er interaktive — de kan ikke automatiseres:

```powershell
.\scripts\login-claude-cli.ps1
.\scripts\configure-claude-token.ps1
```

Det første logger deg inn. Det andre lagrer et token som de automatiske kjøringene bruker, siden
`claude setup-token` ikke logger inn kommandolinjeverktøyet av seg selv.

## 5. NotebookLM

Når du har fått invitasjonen fra Jalal:

```powershell
.\scripts\login-notebooklm.ps1
```

Den åpner en nettleser der du logger inn med Google-kontoen du oppgav i steg 3.

## 6. Kontroller at alt virker

```powershell
.\scripts\verify.ps1
```

Denne **starter faktisk alle tre MCP-serverne** og snakker protokoll med dem — den sjekker ikke bare
at filer finnes. Regn med et minutt.

Går det fort nok for deg uten den delen:

```powershell
.\scripts\verify.ps1 -Rask
```

Du vil se noe i denne formen:

```
  Filstruktur                            OK
  config.env                             OK
  XSALE                                  OK
        bruker kari@plorea.com
  MySQL                                  OK
  xsale-crm                              OK
        XSALE CRM Server - 16 verktoy
  ============================================================
    Alt bestatt. Du er klar.
```

## 7. Åpne mappen i Claude Code

Åpne **repo-mappen** i Claude Code. Det er der `.mcp.json` og `CLAUDE.md` ligger, og Claude Code leser
MCP-servere fra mappen du åpner — ikke fra en mappe over eller under.

Godkjenn MCP-serverne når du blir spurt.

Prøv så:

> «Hvilke XSALE-saker har jeg på meg?»

Får du din egen saksliste, er alt på plass.

---

## Den automatiske saksassistenten

Kjør én runde manuelt først, så du ser hva den gjør:

```powershell
.\scripts\run-auto-xsale.ps1
```

Den tar den eldste av **dine** ubehandlede saker, undersøker den, og skriver tre filer i saksmappen
din. Den sender ingen e-post og lukker ingen saker.

Hvilke saker som plukkes bestemmes av **din innlogging**, ikke av noe navn i prompten.

Får du dette svaret, er det ikke en feil:

```
Køen er tom: ingen XSALE-saker med status Ny eller Under behandling som ikke er behandlet.
```

Det betyr at du ikke har ubehandlede saker med status `NEW` eller `ASSIGNED` akkurat nå. Køen tar
bevisst bare saker den ikke har sett før.

### Rutiner må du lage selv

**Du finner ingen ferdig rutine etter installasjonen, og det er riktig.**

Claude Codes rutiner er lokal brukertilstand — de lagres i `~\.claude\scheduled-tasks\` på din egen
maskin, ikke i dette repoet. De kan ikke deles gjennom Git, og en restart av Claude Code får dem ikke
til å dukke opp.

Har du sett en kollega ha en rutine for dette, må du opprette din egen. Det tar et minutt, og teksten
du skal lime inn ligger klar i [routine/OPPSETT.md](routine/OPPSETT.md).

Automatisk kjøring er forøvrig **valgfritt**. Mange kjører assistenten manuelt når de trenger den.

## Saksoversikt i nettleser

Valgfri, krever Node.js:

```powershell
cd app
npm install
npm run dev
```

Åpne `http://localhost:4317`.

---

## Når noe ikke virker

**Kjør `.\scripts\verify.ps1` først.** Den peker på hvilket ledd som feiler. Rett feilene ovenfra og
ned — de henger ofte sammen.

| Symptom | Sannsynlig årsak |
|---|---|
| «kjøring av skript er deaktivert» | Se steg 0 |
| «Fant ikke Claude Code CLI» | Sett `CLAUDE_CLI_PATH` i `config.env` til full sti til `claude.exe` |
| «Kan ikke dekrypteres» | Legitimasjonen er laget på en annen maskin. Kjør `oppsett.ps1` på nytt |
| «Fila er tom» | En passorddialog ble avbrutt. Kjør `oppsett.ps1` på nytt |
| Verktøyene mangler i Claude Code | Du har åpnet feil mappe. Åpne repo-mappen |
| NotebookLM feiler | Har du fått invitasjonen? Kjør `login-notebooklm.ps1` |

Får du ikke løst det, ta med hele utdataen fra `verify.ps1` når du spør.
