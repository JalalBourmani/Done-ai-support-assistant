# Auto-XSALE

Lokal, **read-only** frontend for XSALE-saksassistenten. Den leser saksmappene
som saksassistenten skriver til, og viser dem som et ryddig dashboard — slik at
du raskt kan se hva agenten har jobbet med, hvilke saker som er behandlet,
hvilke utkast som finnes, hva som gjenstår, og om agenten er våken eller i standby.

> Appen **leser kun** filer. Den skriver, sletter eller flytter aldri noe, og
> sender aldri e-post eller gjør endringer i XSALE.

---

## Kom i gang

```bash
npm install
npm run dev
```

Åpne deretter **http://localhost:4317**.

## Pek på riktig saksmappe

Stien til Auto-XSALE-mappa settes via miljøvariabelen `AUTO_XSALE_DIR` i
`.env.local`:

```ini
AUTO_XSALE_DIR=C:\Users\<ditt-brukernavn>\Documents\Auto-XSALE
```

`scripts\install.ps1` setter denne for deg. Kjører du appen manuelt, må du opprette `.env.local`
selv.

**Er variabelen ikke satt, nekter appen å starte.** Det er med vilje: en tilbakefallsverdi som peker
på en mappe du ikke har, gir en tom saksliste — og en tom saksliste er ikke til å skille fra en rolig
uke. Bedre å si hva som mangler.

Mappen skal ligge **utenfor** repoet. Kundedata skal ikke i Git.

---

## Sider

| Side | Hva den viser |
| --- | --- |
| **Oversikt** (`/`) | Antall saker på deg, behandlet/ubehandlet, siste behandlede sak, neste agent-kjøring, agentstatus, og de sist behandlede sakene. |
| **Behandlede saker** (`/cases`) | Tabell over alle lokale saksmapper med søk + filter, filer per sak, og behandlet-status. |
| **Saksdetalj** (`/cases/<nr>`) | Metadata + fil-liste med innebygd viser: Markdown rendres pent, JSON formateres, CSV vises som tabell. Her kan saken **markeres som løst** (eller gjenåpnes). |
| **Mine XSALE-saker** (`/assigned`) | Saker satt på deg (saksnr, kunde, emne, status, opprettet, om agenten har behandlet/løst, lenke til lokal mappe). |
| **Løste saker** (`/resolved`) | Saker du har markert som løst, sortert etter når de ble løst. |
| **Agent** (`/agent`) | Agentstatus (våken/standby), neste/siste kjøring, antall behandlet i dag/uke, siste behandlede sak. |

## API-lag

Alle sider bygger på det samme datalaget (`lib/cases.ts`), som også eksponeres
som JSON-API:

- `GET /api/cases` — alle lokale saker
- `GET /api/cases/:caseNumber` — én sak med fildetaljer
- `GET /api/cases/:caseNumber/files/:fileName` — innhold i én fil (path-sikret)
- `GET /api/agent-status` — agentstatus
- `GET /api/assigned-cases` — saker tildelt den innloggede brukeren
- `POST /api/cases/:caseNumber/resolve` — marker sak som løst
- `DELETE /api/cases/:caseNumber/resolve` — gjenåpne sak

## «Løst»-status (din arbeidsflyt)

Når du har svart ut en sak kan du **markere den som løst** inne på saken. Da
flyttes den fra «Behandlede saker» til «Løste saker».

Denne statusen lagres i **én skjult fil** i roten av Auto-XSALE-mappa:
`.auto-xsale-ui.json`. Agentens saksmapper røres ikke — appen er fortsatt
read-only mot saksdataene. Fila ligger sammen med dataene dine (ikke i
app-koden), så den overlever når du kopierer over appen på nytt.

---

## «Behandlet»-logikk

En sak regnes som **behandlet** når både `troubleshooting.md` og
`draft_reply.md` finnes i saksmappa.

## Agentstatus

Status avledes automatisk fra endringstidspunktet på filene i saksmappene
(siste kjøring = sist endrede sak, antall i dag/uke, neste kjøring = siste +
intervall). For **eksakt** styring kan agenten legge en `agent-status.json` i
roten av Auto-XSALE-mappa:

```json
{
  "state": "working",
  "lastRun": "2026-06-15T08:00:00Z",
  "nextRun": "2026-06-15T08:30:00Z",
  "intervalMinutes": 30
}
```

Finnes fila, overstyrer den de avledede verdiene.

## Mine XSALE-saker (live kobling senere)

I dag bygges «Mine XSALE-saker» fra `case_raw.json`-øyeblikksbildene agenten
allerede har hentet — ekte data, tydelig merket som lokalt øyeblikksbilde.
Når en live XSALE MCP/API kobles til, byttes kilden ut ett sted:
`app/api/assigned-cases/route.ts` (og `getAssignedCases()` i `lib/cases.ts`).
Datastrukturen er allerede på formen et live-API ville returnert.

---

## Teknisk

- **Next.js 14** (App Router) + **TypeScript** — React-frontend og fil-lesende
  API-lag i én app.
- Egen **midnight-blue** dark theme i ren CSS (`app/globals.css`).
- **react-markdown** + **remark-gfm** for Markdown (tabeller, sjekklister).
- Ingen database, ingen eksterne kall — alt leses fra det lokale filsystemet.
