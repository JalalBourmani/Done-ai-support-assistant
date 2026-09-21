# Forutsetninger — les dette før du installerer

Settet gir deg Claude Code koblet til XSALE, ProTouch-databasene og Amendo-kunnskapsbasen, pluss den
automatiske saksassistenten.

**Bruk 10 minutter på denne siden før du kjører installeren.** Alt under må være på plass først. De
fleste punktene har du sannsynligvis allerede.

---

## Sjekkliste

| # | Krav | Har du det? |
|---|---|---|
| 1 | Windows 10/11 med PowerShell 5.1 eller nyere | Følger med Windows |
| 2 | Claude Code, installert og innlogget | Egen lisens kreves |
| 3 | Python 3.10 eller nyere, tilgjengelig som `python` i PATH | Sjekk med `python --version` |
| 4 | Git | Sjekk med `git --version` |
| 5 | Node.js 18 eller nyere — **bare** hvis du vil ha saksoversikten i nettleser | `node --version` |
| 6 | Egen XSALE-bruker | Du har den alt |
| 7 | Egen MySQL-bruker på `ws.tellix.no` (phpMyAdmin) | Du har den alt |
| 8 | **Kontornett eller VPN** — for MySQL-delen | Se under |
| 9 | Atlassian API-token med omfang — for Confluence | Lager du selv — se under |
| 10 | Tilgang til GitHub-repoet | **Må bes om — se under** |

### Rask sjekk

Kjør dette i PowerShell. Alle fire skal svare med et versjonsnummer:

```powershell
python --version; git --version; node --version; claude --version
```

Mangler `node`, kan du installere senere — da hopper du bare over saksoversikten.
Mangler noen av de tre andre, ordne det først.

---

## To ting du må be om

Gjør begge **før** du starter installasjonen, så du ikke må vente midt i den.

**1. Tilgang til GitHub-repoet.** Repoet er privat. Send Jalal GitHub-brukernavnet ditt, og godta
invitasjonen som kommer på e-post. Uten den feiler `git clone` med `Repository not found` — en melding
som ikke antyder at problemet er tilgang.

**2. Confluence-token.** Kunnskapsserveren leser fra Confluence-rommene og fra det offentlige
hjelpesenteret på support.amendo.no. Hjelpesenteret krever ingen innlogging; Confluence gjør.

Lag tokenet selv under **id.atlassian.com → Security → API tokens → Create API token with scopes**.
Velg Confluence-appen og lesetilgang til sider og rom. Et **klassisk** token uten omfang virker
ikke mot den API-flaten serveren bruker.

Hopper du over dette, virker hjelpesenteret likevel, og `kunnskapsstatus` sier hva som mangler.

---

## 🔴 Nettverk — les dette før du feilsøker et passord

**`ws.tellix.no` slipper bare inn åpnede IP-adresser.** Sitter du hjemme uten VPN, feiler
MySQL-innloggingen selv med helt riktig brukernavn og passord.

Og feilmeldingen hjelper deg ikke: phpMyAdmin svarer

```
Authentication Error: Login to phpMyAdmin failed. Please check DB_USER and DB_PASSWORD.
```

…uansett årsak. Får du den, **sjekk nettverket før du sjekker passordet.**

Dette gjelder bare MySQL-delen. XSALE og kunnskapsserveren virker hvor som helst, så du kan fullføre resten
av installasjonen og kjøre dette senere:

```powershell
.\scripts\oppsett.ps1 -Bare mysql
```

---

## Legitimasjon — hvordan den håndteres

Du skriver inn dine egne brukernavn og passord én gang under installasjonen. De lagres kryptert med
Windows DPAPI i `secrets\*.xml`.

**Det betyr i praksis:**

- Krypteringen er bundet til **din Windows-bruker på denne maskinen**. Filene kan ikke dekrypteres av
  noen andre, heller ikke av en administrator på en annen maskin.
- `secrets\` er utelatt fra Git. Den følger aldri med når du henter oppdateringer eller deler repoet.
- Bytter du maskin, må du kjøre legitimasjonsoppsettet på nytt. Å kopiere `secrets\`-filene virker ikke.

**Du skal aldri:**

- Skrive et passord inn i `config.env`, `.mcp.json` eller noen annen tekstfil
- Dele `secrets\`-mappen
- Committe noe som inneholder legitimasjon

Blir du bedt om et passord i en dialogboks som du avbryter, blir filen liggende **tom**. Det er en
klassisk felle — `verify.ps1` fanger den og sier det tydelig.

---

## Hva settet får tilgang til

Verdt å være bevisst på, siden det er kundedata:

| Server | Tilgang | Skriverettigheter |
|---|---|---|
| `xsale-crm` | Saker, kunder, ordre, kommunikasjon | Kommentar, kundesvar og statusendring **som deg** — se autonominivåer |
| `mysql-query-server` | ProTouch-databasene via phpMyAdmin | **Ingen.** Kun SELECT/SHOW/DESCRIBE/EXPLAIN |
| `kunnskap` | Confluence-rommene og support.amendo.no | Ingen |

**Den automatiske køen har ingen skrivetilgang til XSALE eller databasen.** Den kjører med en
eksplisitt hviteliste der bare lesende XSALE-verktøy er med — `create_case` og `add_case_comment` er
holdt utenfor med vilje. Den sender aldri e-post og lukker aldri saker.

Den **skriver til disk**, og det må den: analyser og svarutkast legges i saksmappen din. Det betyr at
den har `Write`, `Edit` og `Bash` lokalt. Vær bevisst på det — den er ikke uten skriverettigheter,
den er uten skriverettigheter *mot kundesystemene*.

Skrivetilgangen i `xsale-crm` gjelder bare når du selv ber om det i en samtale, og handlingen
registreres på din bruker — så det er ditt navn som står som forfatter.

---

## Etter installasjonen

Saksmappene med kundedata legges **utenfor** repoet, i en mappe du velger under installasjonen
(standard `%USERPROFILE%\Documents\Auto-XSALE`).

Det er bevisst: kundedata skal ikke kunne havne i Git ved et uhell. Ikke flytt dem inn i
repo-mappen.

---

## Når noe ikke virker

Kjør alltid dette først:

```powershell
.\scripts\verify.ps1
```

Den sjekker hvert ledd og sier hva som mangler — om det er Python, en tom legitimasjonsfil, manglende
Confluence-token eller en server som ikke starter. Ta med utdataen når du ber om hjelp.

Neste steg: [KOM-I-GANG.md](KOM-I-GANG.md)
