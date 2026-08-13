# Automatisk kjøring av saksassistenten

Saksassistenten kan kjøre av seg selv med jevne mellomrom. Det er **valgfritt** — mange kjører den
manuelt når de trenger den, og det er helt greit.

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

1. Åpne Claude Code i repo-mappen
2. Åpne **Routines**-panelet
3. Lag en ny rutine med denne instruksjonen:

```
Kjør .\scripts\run-auto-xsale.ps1 fra repo-mappen.
Rapporter kort hvilken sak som ble behandlet og hvilke filer som ble laget.
Ikke gjør noe annet.
```

4. **La intervallet stå tomt** hvis du bare vil kunne starte den manuelt. Setter du et intervall,
   husk at den bare kjører når Claude Code faktisk er åpent.

### Sett den manuell først

Det er en god vane å la den være manuell de første dagene. Da bestemmer du når den går, og du
oppdager tidlig hvis noe i saksmengden din gjør at utkastene bommer.

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
