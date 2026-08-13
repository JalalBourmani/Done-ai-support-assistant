# MySQL phpMyAdmin Bridge MCP Server

Dette er en tilpasset Model Context Protocol (MCP) server som gir sikker, skrivebeskyttet (read-only) tilgang til en MySQL/MariaDB database ved å fungere som en HTTP-bro (bridge) mot phpMyAdmin. Dette løser problemet med at direkte databasetilkobling (f.eks. port 3308) er blokkert bak en brannmur.

Serveren kjører som MCP-server i Claude Code, og lar deg kjøre trygge SQL-spørringer direkte fra samtalen.

## Funksjoner
- **Skrivebeskyttet sikkerhet:** Bare SELECT, SHOW, DESCRIBE og EXPLAIN-spørringer tillates. Alle endringsspørringer (som INSERT, UPDATE, DELETE, DROP) blokkeres automatisk av serveren før de i det hele tatt sendes til phpMyAdmin.
- **HTTP Bridge:** Logger automatisk inn i phpMyAdmin, henter CSRF-tokens, utfører SQL-spørringen via phpMyAdmins AJAX API (`import.php`), og tolker tabellresultatene tilbake til strukturert JSON.
- **Håndtering av NULL-verdier:** Kolonner som inneholder database-NULL (markert med `class="null"` eller `data-type="null"` av phpMyAdmin) blir korrekt tolket som JSON `null`.
- **Ekskludering av handlingskolonner:** Unngår at phpMyAdmins rediger/slett/kopier-kolonner eller avmerkingsbokser havner i resultat-JSONen ved å ignorere tabellelementer med klassen/attributten `print_ignore`.
- **Fullstendige resultatsett:** Sender eksplisitt `session_max_rows`, og sammenligner alltid antall returnerte rader med totalen phpMyAdmin oppgir. Se under.

---

## ⚠️ Avkutting av resultatsett

phpMyAdmin viser **25 rader per side** som standard, og svaret inneholder ingen indikasjon på at noe
er utelatt. En spørring som treffer 1 570 rader ser derfor ut som et fullstendig svar med 25 rader.

Det førte til feilkonklusjoner i en reell sak, der hendelsesvinduet hadde 38 rader og
`product`-tabellens 45 kolonner ble vist som 25.

Serveren håndterer dette på to nivåer:

1. `session_max_rows` sendes eksplisitt med hver spørring (`PMA_MAX_ROWS`, standard 10 000).
2. Totalen parses fra phpMyAdmins egen `Showing rows 0 - 24 (38 total, ...)` — med
   `unlim_num_rows` som reserve — og sammenlignes med antall parsede rader.

Blir resultatet likevel avkuttet, returneres et **JSON-objekt** i stedet for den vanlige lista:

```json
{
  "truncated": true,
  "total_rows": 1570,
  "returned_rows": 10000,
  "warning": "INCOMPLETE RESULT: ...",
  "rows": [ ... ]
}
```

Et slikt svar skal behandles som ufullstendig: snevre inn med `WHERE`, aggreger med
`COUNT`/`GROUP BY`, eller hev `PMA_MAX_ROWS`.

## Om `REPLACE()` og `INSERT()`

`REPLACE` og `INSERT` er både DML-kommandoer og vanlige strengfunksjoner i MySQL. Kontrollen
blokkerer dem bare når de *ikke* følges av `(`, slik at `SELECT REPLACE(navn,' cm','')` går gjennom
mens `REPLACE INTO` avvises. Det er trygt fordi spørringen alt må starte med en skrivebeskyttet
kommando og ikke kan inneholde et andre statement.

---

## Installasjon

1. Sørg for at Python 3 er installert på din maskin.
2. Installer nødvendige avhengigheter i denne mappen:
   ```bash
   pip install -r requirements.txt
   ```

---

## Konfigurasjon

Du skal normalt ikke konfigurere denne serveren manuelt. Den startes av settet:

```powershell
.\scripts\run-mcp.ps1 -Server mysql
```

`run-mcp.ps1` henter `DB_USER` og `DB_PASSWORD` DPAPI-kryptert fra `secrets\mysql.xml` og setter dem
som miljøvariabler i serverprosessen. Ingenting havner på disk i klartekst, og `generated\mcp.json`
inneholder aldri legitimasjon — bare stien til oppstartsskriptet.

Legitimasjonen legges inn med `.\scripts\oppsett.ps1`, som også tester innloggingen før den lagrer.

> **Skriv aldri et reelt passord inn i en konfigurasjonsfil.** Verken her, i `config.env` eller i
> `.mcp.json`. Alle tre ligger i eller ved et Git-repo.

---

## Miljøvariabler

| Variabel | Standard | Beskrivelse |
|---|---|---|
| `PMA_URL` | `https://ws.tellix.no/phpmyadmin/` | phpMyAdmin-endepunkt |
| `DB_USER` | — | **Påkrevd.** Databasebruker |
| `DB_PASSWORD` | — | **Påkrevd.** Settes via `run-mcp.ps1`, ikke i fil |
| `DB_NAME` | `protouch` | Database spørringene kjøres mot |
| `PMA_MAX_ROWS` | `10000` | Radgrense per spørring. Overstiges den, varsles det eksplisitt |
| `PMA_LOGIN_TIMEOUT` | `120` | Sekunder for innlogging. `ws.tellix.no` er målt til 30–38 s når den er treg; den gamle grensen på 15 s gjorde treghet til hard feil |
| `PMA_QUERY_TIMEOUT` | `180` | Sekunder for én spørring |

Ugyldige eller ikke-positive verdier ignoreres, slik at en skrivefeil ikke slår av radgrensen.

---

## Utvikling & Testing

For å kjøre enhetstestene som verifiserer spørringsvalideringen og parsing av HTML-tabeller:
```bash
pytest test_mcp_server.py -v
```
