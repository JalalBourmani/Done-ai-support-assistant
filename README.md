# Done.ai Support Assistant

Claude Code koblet til verktøyene vi bruker i support: XSALE, ProTouch-databasene og
Amendo-kunnskapsbasen. Pluss en saksassistent som går gjennom saker på egen hånd og skriver
svarutkast du går gjennom.

Du installerer med dine egne innlogginger. Ingenting deles mellom brukere.

---

## Hva du får

**Tre verktøy i Claude Code:**

| Verktøy | Hva du kan spørre om |
|---|---|
| `xsale-crm` | Saker, kunder, ordre, kommunikasjon. Kan opprette sak og kommentar som deg |
| `mysql-query-server` | Oppslag i ProTouch-databasene. **Skrivebeskyttet** |
| `notebooklm-mcp` | Rutiner og produktkunnskap fra Confluence-artiklene |

**Saksassistenten (Auto-XSALE).** Tar den eldste ubehandlede saken din, undersøker den mot XSALE og
databasen, og skriver en analyse og et svarutkast til disk. Den sender aldri e-post og lukker aldri
saker.

**Saksoversikt i nettleser.** Enkel oversikt over behandlede saker, med tre arbeidstilstander —
åpen, venter på svar, løst — og bildevisning for vedlegg fra kunder. Valgfri.

---

## Kom i gang

**1. Les [FORUTSETNINGER.md](FORUTSETNINGER.md) først.** Tar 10 minutter, og sparer deg for å stå fast
midt i installasjonen. Det eneste du må be om på forhånd er invitasjon til NotebookLM-prosjektet.

**2. Klon og installer:**

```powershell
git clone https://github.com/<konto>/Done-ai-support-assistant.git
cd Done-ai-support-assistant
.\scripts\install.ps1
```

**3. Legg inn din legitimasjon.** Du blir spurt om fornavn, XSALE, MySQL og Google-adresse. Hver
innlogging testes med en gang, så du vet at den virker før du går videre:

```powershell
.\scripts\oppsett.ps1
```

**4. Logg inn i Claude Code.** To steg, begge interaktive:

```powershell
.\scripts\login-claude-cli.ps1
.\scripts\configure-claude-token.ps1
```

**5. NotebookLM,** når du har fått invitasjonen:

```powershell
.\scripts\login-notebooklm.ps1
```

**6. Kontroller at alt virker:**

```powershell
.\scripts\verify.ps1
```

`verify.ps1` sjekker hvert ledd og sier presis hva som mangler. Får du «alt bestått», er du klar.
Får du en feil, står det hva den er — ta med utdataen hvis du ber om hjelp.

Full gjennomgang: [KOM-I-GANG.md](KOM-I-GANG.md)

---

## Om legitimasjon

Du skriver inn dine egne brukernavn og passord én gang. De lagres kryptert med Windows DPAPI i
`secrets\`, som er utelatt fra Git.

Krypteringen er bundet til **din Windows-bruker på din maskin**. Filene kan ikke dekrypteres av noen
andre — heller ikke av en administrator, heller ikke på en annen maskin. Bytter du maskin, kjører du
legitimasjonsoppsettet på nytt.

**Skriv aldri et passord inn i `config.env`, `.mcp.json` eller noen annen tekstfil i dette repoet.**

## Sikkerhetsegenskaper som er med vilje

- **Databasen er skrivebeskyttet.** Bare `SELECT`, `SHOW`, `DESCRIBE` og `EXPLAIN` slipper gjennom.
  Alt annet avvises før det sendes.
- **Saksassistenten har ingen skriverettigheter.** Den kjører med en eksplisitt hviteliste av kun
  lesende verktøy.
- **Ingen e-post sendes automatisk.** Svarutkast skrives til disk. Alt som går ut, går ut fra deg.
- **Saker lukkes ikke automatisk** i XSALE.
- **Kundedata ligger utenfor repoet**, i en mappe du velger under installasjonen. Det er umulig ved
  konstruksjon å committe dem ved et uhell.

---

## Struktur

```
scripts/        installasjon, legitimasjon, verifisering, saksassistent
prompts/        prompten saksassistenten kjører
servers/        de tre MCP-serverne
templates/      CLAUDE.md og mcp.json — genereres med dine stier
routine/        oppsett av automatisk kjøring
app/            saksoversikt i nettleser (valgfri)
examples/       oppdiktet eksempel som viser formen på output
```

Disse kjører du normalt aldri selv:

| Fil | Rolle |
|---|---|
| `scripts\common.ps1` | Delt bibliotek de andre skriptene laster |
| `scripts\run-mcp.ps1` | Starter én MCP-server. Kalles av `generated\mcp.json` |
| `scripts\mcp_smoketest.py` | Håndtrykk mot en MCP-server. Brukes av `verify.ps1` |
| `scripts\backfill_case_raw.py` | Lager `case_raw.json` i gamle saksmapper som mangler den, slik at de vises riktig i saksoversikten. Kjør med `--dry-run` først |

## Oppdateringer

```powershell
git pull
.\scripts\install.ps1     # trygg å kjøre om igjen
.\scripts\verify.ps1
```

`install.ps1` er idempotent. Den overskriver ikke `config.env`, `secrets\` eller din `CLAUDE.md`.

## Når noe ikke virker

Kjør `.\scripts\verify.ps1` først, og ta med utdataen. Den skiller mellom manglende Python, tom
legitimasjonsfil, manglende NotebookLM-innlogging og en server som ikke starter — så feilsøkingen
begynner på riktig sted.
