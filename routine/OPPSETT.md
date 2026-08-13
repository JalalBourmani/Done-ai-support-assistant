# Automatisk kjøring av saksassistenten

Saksassistenten kan kjøre av seg selv med jevne mellomrom. Det er **valgfritt** — mange kjører den
manuelt når de trenger den, og det er helt greit.

> ### Du har ingen rutine etter installasjonen
>
> Det er ikke en feil, og en restart av Claude Code hjelper ikke.
>
> Rutiner er **lokal brukertilstand**. De lagres i `~\.claude\scheduled-tasks\<id>\SKILL.md` på din
> egen maskin, og følger derfor ikke med repoet. Har en kollega en rutine for dette, kan den ikke
> kopieres eller deles — du lager din egen etter oppskriften under.

> **Kjør den manuelt et par ganger først.** Se hva den skriver, og om utkastene er nyttige for
> saksmengden din, før du setter den til å gå automatisk.
>
> ```powershell
> .\scripts\run-auto-xsale.ps1
> ```

---

## Hva den gjør per runde

Én sak. Den eldste av **dine** ubehandlede XSALE-saker med status `NEW` eller `ASSIGNED` som ikke
allerede har en mappe.

Hvilke saker som plukkes bestemmes av din XSALE-innlogging, ikke av noe navn. Kollegene dine får sine
egne saker, ikke dine.

Den skriver tre filer i saksmappen din, og **sender ingenting**. Ingen e-post, ingen endring i XSALE,
ingen lukkede saker.

---

## Alternativ A — Claude Code Routine (anbefalt)

Kjører mens Claude Code er åpent. Enklest, og du ser resultatet med en gang.

### Raskeste vei: la agenten sette den opp

Åpne Claude Code i repo-mappen og lim inn dette:

```
Sett opp en rutine som kjører saksassistenten i dette repoet.

Rutinen skal ha denne instruksjonen, ordrett:

---
Kjør .\scripts\run-auto-xsale.ps1 fra repo-roten. Ingenting annet.

Rapporter deretter kort:
- hvilket saksnummer som ble behandlet, og for hvilken kunde
- hvilke filer som ble opprettet
- stien til loggfila
- eventuelle punkter skriptet ba brukeren kontrollere manuelt

Regler:
- Ikke send e-post. Ikke lukk, endre eller kommenter saker i XSALE.
- Ikke rediger svarutkastene skriptet lager. De skal leses av et menneske først.
- Svarer skriptet at køen er tom, er det riktig oppførsel. Rapporter det i én
  setning og avslutt. Ikke let etter annet arbeid.
- Feiler skriptet, rapporter feilmeldingen og stopp. Ikke prøv på nytt, og ikke
  forsøk å reparere noe.
---

La intervallet stå tomt, slik at jeg starter den manuelt til jeg har sett hva den gjør.
Bekreft hva du satte opp når du er ferdig.
```

Klarer ikke agenten å opprette rutiner, gjør du det manuelt — se under. Teksten er den samme.

### Manuelt i Routines-panelet

1. Åpne Claude Code i repo-mappen
2. Åpne **Routines**-panelet, lag en ny rutine
3. Lim inn instruksjonen mellom `---`-linjene over
4. **La intervallet stå tomt** hvis du bare vil starte den manuelt

### Hvorfor instruksjonen er så streng

Hver regel dekker noe som faktisk kan gå galt i en uovervåket kjøring:

| Regel | Hva den hindrer |
|---|---|
| Ingenting annet enn skriptet | At agenten «hjelper til» med å sende utkastet eller lukke saken |
| Ikke rediger utkastene | At et menneske aldri får lest det som går til kunden |
| Tom kø er riktig | At agenten leter etter arbeid som ikke finnes |
| Ikke prøv på nytt | At en feil gjentas i løkke og spiser budsjett |

Skriptet har egne vakter — hvitelisten uten skrivende XSALE-verktøy, og stoppen hvis noen legger inn
ett. Reglene over er laget for **agenten rundt** skriptet, som ikke er begrenset på samme måte.

### Sett den manuell først

La den være manuell de første dagene. Da bestemmer du når den går, og du oppdager tidlig hvis noe i
saksmengden din gjør at utkastene bommer.

Setter du et intervall senere: **velg minst 30 minutter.** En runde kan ta flere minutter, og
skriptet har ingen lås mot at to runder overlapper.

---

## Alternativ B — Windows Oppgaveplanlegging

Kjører uten at Claude Code er åpent. Krever at du har lagret et Claude-token
(`configure-claude-token.ps1`).

```powershell
# Hver time i arbeidstiden
.\scripts\register-scheduled-task.ps1 -EveryMinutes 60

# Bare manuell start — ingen automatisk trigger
.\scripts\register-scheduled-task.ps1 -Manual
```

Start den manuelt:

```powershell
Start-ScheduledTask -TaskName "Auto-XSALE Claude Code"
```

> **Ikke bruk `Disable-ScheduledTask` for å sette den på pause.** En deaktivert oppgave nekter også å
> starte manuelt. Vil du ha den i ro, registrer den på nytt med `-Manual`.

---

## Loggene

Hver runde skriver en logg i `logs\auto-xsale-<tidspunkt>.log`. Der står hvilken sak som ble
behandlet, hva som ble funnet, og hva du må kontrollere manuelt.

Loggene er utelatt fra Git — de inneholder kundedata.

Rydd i dem av og til. De blir mange.

---

## Hvis den ikke gjør noe

Er alle sakene dine allerede behandlet, svarer den:

```
Køen er tom: ingen XSALE-saker med status Ny eller Under behandling som ikke er behandlet.
```

Det er riktig oppførsel. Kø-regelen er at en sak behandles **én gang** — den tas ikke opp igjen bare
fordi status endret seg i XSALE. Vil du at den skal se på en sak på nytt, be om saksnummeret
eksplisitt i en vanlig samtale.

## Hvis den feiler

```powershell
.\scripts\verify.ps1
```

Vanligste årsak til at en automatisk kjøring stopper mens den manuelle virker: Claude-tokenet mangler
eller er utløpt. Kjør `login-claude-cli.ps1` og `configure-claude-token.ps1` på nytt.
