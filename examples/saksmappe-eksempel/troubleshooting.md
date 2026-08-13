# Sak 41234 — NORDVIK SPORT AS — kassen mister forbindelse til terminalen

Undersøkt 04.03.2026. Klientdatabase: `protouch_client_9999_1600000000` (klient 9999).
**Alle oppslag skrivebeskyttet.**

> Dette er et **oppdiktet eksempel** som viser formen saksassistenten skriver i. Kunde, saksnummer,
> serienumre og datoer er funnet på. Ingen reell sak.

## Kort oppsummert

Kassen mister forbindelsen til betalingsterminalen omtrent én gang i timen. Årsaken er ikke
terminalen, men at kassens IP-adresse endres av DHCP mens terminalen har den gamle adressen lagret.

Riktig tiltak er en fast IP-reservasjon i ruteren. Det er ikke noe å endre i ProTouch.

---

## ✅ Bekreftede funn

**Terminalen har byttet IP-adresse tre ganger på fire dager.** Fra `pos_terminal_log`:

| Tidspunkt | IP | Hendelse |
|---|---|---|
| 01.03 08:12:04 | 192.168.1.104 | tilkoblet |
| 02.03 06:30:11 | 192.168.1.107 | tilkoblet, ny adresse |
| 03.03 07:02:55 | 192.168.1.112 | tilkoblet, ny adresse |

**14 avbrudd i loggen, alle med samme mønster.** `connection_lost` etterfulgt av `reconnect` innen
40–90 sekunder. Ingen av dem faller sammen med en transaksjon, så ingen salg har feilet.

**Terminalen er 11 måneder gammel** (S/N `P400-000123456`, i drift siden 04.04.2025) og har ingen
feilkoder i `terminal_error`. Maskinvaren er altså ikke problemet.

**Antall rader kontrollert:** spørringen mot `pos_terminal_log` ga 14 rader, og `COUNT(*)` for samme
periode ga 14. Ingen avkutting.

## 🟡 Sannsynlig vurdering

Butikken har sannsynligvis kort DHCP-leietid på ruteren. Hver gang leien fornyes får kassen en ny
adresse, mens terminalen fortsatt peker på den forrige — derav avbruddet, og derav at den kommer
tilbake av seg selv når terminalen søker på nytt.

Det forklarer både hyppigheten og at ingen transaksjoner har feilet.

## ⚠️ Må kontrolleres manuelt

Dette får jeg ikke svar på fra databasen:

1. **DHCP-leietiden i ruteren.** Er den under 24 timer, er hypotesen bekreftet.
2. **Om butikken har flere enheter på samme nett** som kan konkurrere om adressene.
3. **Hvem som administrerer nettverket** — kunden selv eller en ekstern leverandør. Det avgjør om vi
   kan gjøre endringen eller må be dem om det.

## Anbefalt tiltak

1. Sett fast IP-reservasjon for kassen i ruteren, utenfor DHCP-området
2. Legg den faste adressen inn i terminaloppsettet
3. Følg med i ett døgn — avbruddene skal forsvinne helt, ikke bli sjeldnere

Ingen endringer i ProTouch. Ingen SQL.

## Merknad om verktøyet

`mysql-query-server` er skrivebeskyttet. Alle oppslag her er `SELECT`, og databasen er ikke endret.
