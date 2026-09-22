---
name: sak
description: Ta opp en XSALE-sak i utkastmodus — undersøk, kommenter internt, skriv troubleshooting.md og draft_reply.md som brukeren leser og sender selv. Bruk når brukeren skriver /sak, ber om å se på et saksnummer, eller ber om et svarutkast. Dette er standardmodus; jeg sender ikke e-post og lukker ikke saker her.
---

# Utkastmodus

Brukeren er til stede. Jeg undersøker og legger fram; hen leser og sender.

**Autonominivået skal stå på `les` eller `kommenter`.** Sjekk med
`get_autonomy` hvis du er usikker. Er det `svar` eller `full`, si det — da har
brukeren delegert noe, og da er det `/delegert` som gjelder, ikke denne.

## Rekkefølge

1. **Les saken.** `get_case_by_serial`, og `get_case_emails` når det finnes
   korrespondanse. Aldri konkluder på emnefeltet alene.
2. **Sjekk historikken hos kunden.** `find_customer` og
   `list_cases_for_customer`. XSALE ignorerer tekstfiltre, så et søk som ser
   tomt ut kan skjule ti saker — det har skjedd.
3. **Slå opp i `kunnskap`** før du konkluderer med at noe ikke er
   dokumentert. Null treff betyr at emnet er udokumentert der du søkte.
4. **Bruk MySQL** bare når saken trenger faktadata fra ProTouch. Kontroller
   alltid `COUNT(*)` mot antall rader du fikk — et avkuttet resultat ser
   identisk ut med et fullstendig.
5. **Skriv saksmappen** under `Auto-XSALE/<saksnummer>/`:
   `troubleshooting.md` og `draft_reply.md`. Formatet står i
   `prompts/auto-xsale-saksassistent.md` — les den for `case_raw.json` og
   resten.
6. **Kommenter internt i XSALE** med funnene, hvis nivået tillater det.
7. **Legg fram** hva som er bekreftet, hva som er sannsynlig, og hva brukeren
   må kontrollere manuelt. Det skillet er det viktigste jeg leverer.

## Tre feil jeg har gjort som denne rekkefølgen finnes for

**Konklusjon fra en delmengde.** Jeg meldte et flåtetall basert på 10 000
rader av 887 983, fordi hjelpefunksjonen min kastet `truncated`-flagget.

**Fravær av feil brukt som bevis.** `wp_woo_sync_log_activity` fører bare
feil. Jeg var sekunder fra å melde at nettbutikksynken var brukket for alle
kunder, fordi loggen var full av rader med `status=0`.

**«Finnes ikke dokumentert».** Jeg sa det om BAX-bestilling for eksterne
gavekort. Prosedyren lå i Confluence, oppdatert to uker før, og kunden hadde
ventet fem uker.

## Ikke gjør dette

- Ikke påstå at noe er gjort når det bare er foreslått.
- Ikke takk for et vedlegg du ikke har åpnet.
- Ikke skriv passord, tokens, PIN-koder eller API-nøkler til disk eller til
  svaret. Kundenotatet i XSALE er ofte fullt av dem.
- Ikke påstå en rotårsak du ikke kan peke på dataene for. Skriv «sannsynlig»
  når det er sannsynlig.
- Skriv norsk med æ, ø og å. XSALE lagrer tegnene byte-identisk.
