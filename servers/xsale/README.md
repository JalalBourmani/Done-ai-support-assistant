# XSALE CRM MCP Server

MCP-server mot XSALE CRM. Gir tilgang til saker, kommunikasjon, kundekort og ordre — og kan skrive: kommentere, svare kunder og endre status. Kjøres av `scripts/run-mcp.ps1 -Server xsale`.

## Tilgjengelige verktøy

| Verktøy | Beskrivelse |
|---------|-------------|
| `list_my_cases` | Lister dine åpne saker (filtrerbar på status) |
| `list_unassigned_cases` | Lister ufordelte saker |
| `get_case_details` | Henter fullstendige detaljer for en spesifikk sak |
| `get_case_by_serial` | Finner sak via synlig saksnummer og henter full saksdetalj |
| `get_case_communications` | Henter kommunikasjon/timeline for sak, inkludert relation og activity-logg |
| `get_customer_details` | Henter kundekortinfo, kontaktpersoner, adresser, notater og rå kundedata |
| `get_customer_timeline` | Henter relation/activity-logg for kundekort |
| `get_customer_orders` | Lister ordre koblet til en kunde |
| `get_order_details` | Henter ordredetaljer, ordrelinjer/rådata, relation og activity-logg |
| `get_installation_context` | Samler sak, kundekort, kommunikasjon og ordre til installasjons-/produksjonskontekst |
| `search_cases` | Søker i saker etter tekst |
| `list_case_types` | Lister alle tilgjengelige sakstyper |
| `list_inbound_emails` | Lister nyeste innkommende e-poster |
| `get_logged_user` | Viser info om innlogget bruker |
| `find_customer` | Finner kunde i det lokale registeret (navn, orgnr, e-post, kundenr) |
| `rebuild_customer_index` | Bygger `customer_index.json` på nytt fra XSALE |
| `list_cases_for_customer` | Alle saker på en kunde, via intern `customerId` |
| `get_case_emails` | E-postkorrespondansen på en sak, inn- og utgående |

### Skriveverktøy

| Verktøy | Krever nivå | Beskrivelse |
|---------|-------------|-------------|
| `create_case` | — | Oppretter sak |
| `add_case_comment` | `kommenter` | Intern kommentar |
| `reply_to_customer` | `svar` | **Sender ekte e-post.** `dry_run=True` som standard |
| `set_case_status` | `full` | Endrer status. `dry_run=True` som standard |
| `close_case` | `full` | Setter status `COMPLETED`. `dry_run=True` som standard |
| `edit_case_comment` | `kommenter` | Retter en kommentar **på plass** via `PUT /relation/<id>` |

### Autonominivåer

| Verktøy | Beskrivelse |
|---------|-------------|
| `get_autonomy` | Viser nivå, handlinger utført og saker lest |
| `set_autonomy` | Setter nivå. **Skal bare kalles når Jalal ber om det** |
| `autonomy_report` | Rapport fra revisjonsloggen — utført og avvist |

Fire nivåer: `les` (standard), `kommenter`, `svar`, `full`. Utover nivået gjelder
tre sperrer: to tak (60 skrivehandlinger per serverprosess, 10 per sak),
ingen skriving til en sak
som ikke er lest i samme kjøring, og revisjonslogg i `autonomy_audit.log`.

Varig nivå settes med `XSALE_AUTONOMY` i `config.env`.

## Hvordan skriverutene ble funnet — og hva det kostet

Rutene ble **lest ut av XSALE sin egen aktivitetslogg** (`/activity/`, feltene
`route` og `changelog.groupedDiff`), malt 21.09.2026 pa 626 aktiviteter. Men
loggen viser hvilket **felt som endret seg**, ikke hva klienten sendte — og de
lagrede kolonnenavnene er ikke feltnavnene pa traaden. Resten maatte males paa
en kastesak (48638 pa TESTKUNDE).

### Statusendring: PUT, ikke POST

| Forsok | Resultat |
|---|---|
| `POST /customercase/<id>` med `{id, status}` | «Kunne ikke opprette sak» |
| `POST /customercase/<id>` med hele posten | **OPPRETTER NY SAK.** `success:true`, «Sak opprettet» |
| `PUT /customercase/<id>` med `{status}` | «Kunne ikke finne sak» |
| `PUT /customercase/<id>` med `{id, status}` | «Kunne ikke finne kunde» |
| `PUT` med `id, customerId, subject, typeKey, userId, status` | virker, men **blanker `priority`** |
| `PUT` med de 12 feltene i `CASE_UPDATE_FIELDS` | **virker.** Bare `status` endres |

`POST` ignorerer id-en i stien. Det kostet tre saker (48639–48641) som ble
opprettet der jeg trodde jeg endret en status — med `success: true`. Samme
feilklasse som PowerOffice-bilagene: svaret sier vellykket om noe helt annet
enn det du ba om.

Verifisert paa sak 48641: av 45 felt ble **33 utelatt og alle 33 overlevde**,
inkludert `tagId`, `replyTo`, `requestedBy` og `watchers`. `description` sendes
**bevisst ikke** — den er unodvendig, og aa ekko den tilbake er den siste maaten
aa overskrive HTML-en i saken paa.

`?sendEmail=false` sendes eksplisitt av grensesnittet. Uten den kan en
statusendring varsle kunden.

Statusverdiene er malt pa 2000 levende saker: `NEW`, `ASSIGNED`, `FEEDBACK`,
`ON_HOLD`, `COMPLETED`. **Lukket sak = `COMPLETED`.** Merk ogsaa at XSALE selv
setter `NEW` → `ASSIGNED` naar en supportperson gjor noe med saken.

### E-post: `content` og `to`, og `to` maa vaere en liste

Aktivitetsloggen viser `body`, `receiver`, `sender` — det er de **lagrede**
kolonnenavnene. API-et vil ha noe annet, og valideringsfeilen navnga det:

```
errors: {"content": "This value should not be blank.",
         "to": "This value should not be blank."}
```

`to` som **streng** gir fortsatt «to should not be blank» — en feilmelding som
peker paa riktig felt og likevel er villedende, for feltet var da fylt ut. Den
maa vaere en liste.

Payloaden som validerer:

```json
{"model": "Customercase", "fk": 2994021, "action": "email/send",
 "subject": "...", "content": "<HTML>", "to": ["kunde@eksempel.no"]}
```

Avsender sendes ikke med — XSALE setter den serverside (malt til
`support@plorea.com`).

### Alt som leses tilbake, leses raatt

`get_case_details`, `_format_relation` og `get_case_emails` kjorer verdier
gjennom `clean_html`. Det gjorde at **tre** verifikasjoner meldte «ikke funnet»
paa skrivinger som la helt riktig:

| Verifikasjon | Vasket | Raatt |
|---|---|---|
| Intern kommentar | tagger strippet | `_raa_relasjoner()` |
| Sendt e-post | 522 av 1002 tegn | `_raa_epost()` |
| Sakspost for statusendring | — | `_raa_sak()` |

Vaskeren limer tabellceller sammen (`PunktHva som sjekkesResultat`) mens en
tekstsignatur av raa HTML setter ett mellomrom per tagg. Signaturene kan derfor
ikke sammenlignes.

Etter rettelsen: kommentaren `verified_on_case: true`, e-posten byte-identisk
(1002 sendt, 1002 lagret), og statusendringen melder `endrede_felt: ['status']`
med tom `blankede_felt`.

### Mottakersperren

`reply_to_customer` nekter aa sende til en adresse som ikke hoerer til saken.
Kjente adresser hentes fra tre kilder, og kilden oppgis: e-postene paa saken,
sakens `replyTo`/`inboundEmail`, og kundekortet.

Message-ID-er filtreres bort — `inboundEmail` er en raa headerblokk, og en
Message-ID har samme form som en adresse. Uten filteret godtok sperren
`as8pr09mb4693…@…prod.outlook.com` som gyldig mottaker.

Saker meldt per telefon har ingen e-postadresser (48423 og 48556 er slike). Da
maa adressen hentes fra kundekortet og sendes med `allow_new_recipient=True`.



## Norske tegn

XSALE lagrer æ, ø og å **byte-identisk**. Målt 21.09.2026: en kommentar på 558 tegn og
en e-post på 457 tegn kom tilbake uendret, også `«»`, tankestrek, `é` og `ü`, og i
emnefeltet.

Det er altså ingen teknisk grunn til å transliterere. Jeg gjorde det likevel i fem
kommentarer og to e-poster samme dag — av vane, i kilden — og skrev blant annet «skal
sta uroert», som ikke er et ord i noen rettskrivning.

Derfor finnes `_norskvarsel()`:

- `add_case_comment` og `edit_case_comment` returnerer `sprakadvarsel` med
  feilstavede ord og forslag.
- `reply_to_customer` **nekter å sende**. Overstyres med `tillat_ascii_norsk=True`,
  som er der for engelsk tekst.

Deteksjonen er en kort, entydig ordliste pluss suffiksregler for sammensetninger
(`skriveverktoy`, `dagsoppgjor`), og et signal når norsk prosa ikke har ett enkelt æøå.
`lost` og `mate` står bevisst **ikke** i listen — de er vanlige engelske ord. Engelsk
JIRA-tekst går derfor rent gjennom, slik den skal.

## Rette en kommentar

`PUT /relation/<id>` skriver om en kommentar uten å lage en ny — verifisert på sak 48638,
der antallet relasjoner sto på 7 før og etter. `edit_case_comment` bruker dette, og
rapporterer `ny_kommentar_laget` hvis det likevel skulle skje. Rett skrivefeilen der den
står framfor å stable en rettelse oppå den.

## Oppsett

Serveren startes av settets egen launcher, ikke av en IDE-konfigurasjon:

```powershell
.\scripts\run-mcp.ps1 -Server xsale
```

Den henter legitimasjonen **DPAPI-kryptert** fra `secrets\xsale.xml` og setter
`XSALE_EMAIL` og `XSALE_PASSWORD` som prosessvariabler. Legitimasjonen legges inn med:

```powershell
.\scripts\oppsett.ps1 -Bare xsale
```

**Skriv aldri passordet i en konfigurasjonsfil.** `XSALE_PASSWORD` leses fra miljøet, og
skal komme dit via launcheren. Nøkkelen er kryptert mot Windows-brukeren som la den inn,
så filen kan ikke dekrypteres av andre — og skal heller ikke kopieres mellom maskiner.

`XSALE_URL` settes i `config.env` (se `config.env.example`).

### Miljøvariabler

| Variabel | Standard | Merknad |
|---|---|---|
| `XSALE_URL` | — | **Påkrevd.** Settes i `config.env` |
| `XSALE_EMAIL` | — | **Påkrevd.** Settes via `run-mcp.ps1`, ikke i fil |
| `XSALE_PASSWORD` | — | **Påkrevd.** Settes via `run-mcp.ps1`, ikke i fil |
| `XSALE_AUTONOMY` | `les` | Varig autonominivå. Se tabellen over |

### Registrering i Claude Code

I `.mcp.json` i arbeidsområdet:

```json
"xsale-crm": {
  "type": "stdio",
  "command": "powershell.exe",
  "args": [
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    "<sti til settet>\\scripts\\run-mcp.ps1", "-Server", "xsale"
  ]
}
```

Erstatt `<sti til settet>` med din egen utsjekking. Ingen absolutte stier hører hjemme i
dette repoet.

### Kontroll av at verktøyene faktisk serveres

```powershell
..\..\.venv\Scripts\python.exe sjekk_servert_katalog.py
```

Den starter en ekte serverprosess og teller verktøyene den svarer med over `tools/list`.
Det er ikke det samme som å importere modulen: 21.09.2026 lå fire verktøy under
`mcp.run()` i fila, så dekoratorene kjørte aldri, og katalogen hadde 23 av 27 — mens et
`import` viste alle 27. Testen `test_ingen_verktoy_defineres_etter_serverstarten` fanger
den regresjonen billig, men denne sjekken er den som måler det serveren faktisk gjør.
