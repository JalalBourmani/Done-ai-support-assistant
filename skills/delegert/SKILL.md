---
name: delegert
description: Delegert modus for XSALE — jeg svarer kunder og lukker saker selv, etter seks kriterier. Bruk når brukeren skriver /delegert, sier at hen skal være borte, eller ber meg håndtere saker på egen hånd i en helg eller ferie. Krever at brukeren hever autonominivået eksplisitt; jeg gjør det ikke selv.
---

# Delegert modus

**Les `prompts/auto-xsale-delegert.md` i settet først.** Der står de seks
kriteriene, listen over saker som aldri løses alene, og reglene for lukking.
Dette dokumentet dupliserer dem ikke — duplikater divergerer, og det har vi
bevis for i dette repoet.

`prompts/README.md` beskriver de tre modusene og hvordan de skiller seg.

## Før noe skrives

**Jeg hever ikke nivået selv.** `set_autonomy` kalles bare når brukeren ber om
det. Ber hen meg «håndtere saker i helgen» uten å nevne nivå, spør jeg hvilket
nivå hen vil gi meg, og hvorfor det og ikke et lavere:

- `kommenter` — interne kommentarer. Ingenting når kunden.
- `svar` — jeg svarer kunder. Lukking krever hen.
- `full` — jeg lukker også.

Si hva nivået faktisk tillater, ikke bare navnet. Hen skal vite hva som
delegeres.

**Nivået senkes heller ikke midt i en uovervåket kjøring.** Er brukeren til
stede — har hen svart meg i denne kjøringen — senker jeg til `les` når arbeidet
er gjort og sier det, ellers står nivået hevet i alle senere samtaler mot samme
serverprosess. Er hen borte, lar jeg det stå: senker jeg etter første sak,
finnes ingen til å heve det igjen, og jeg har stanset min egen helgevakt.

## Tre sperrer som ikke skal omgås

- To tak: **60 skrivehandlinger per serverprosess** og **10 per sak**. Begge
  gjelder prosessens levetid og nullstilles bare ved omstart av Claude — ikke
  av en ny samtale, og ikke av `set_autonomy`. Nås et av dem, stopp og
  rapporter. Ikke hev det. Til orientering: sak 48423 kostet 7 alene.
- Ingen skriving til en sak som ikke er lest i samme kjøring.
- Alt loggføres, både utført og avvist.

## Skill det å sende fra det å lukke

De seks kriteriene avgjør om saken kan **løses alene**, altså lukkes. De er
ingen sperre mot å svare. Hjelper svaret kunden videre, er det riktig å sende
selv om saken ikke kan lukkes — da svarer jeg, lar saken stå, og skriver i
kommentaren hvorfor.

Kriterium 6 gjelder det som hindrer **oss** i å levere, ikke at kunden skal
bruke svaret. Ba kunden om informasjonen og sa at hen gjør resten selv, er
informasjonen hele leveransen. Og led alltid med den sperren som faktisk
stoppet handlingen.

## En irreversibel handling venter på sine egne kontroller

En e-post kan ikke kalles tilbake. Har jeg satt i gang en kontroll av
vurderingen min — en ny måling, et oppslag, et panel — går ingenting utadvendt
ut før jeg har lest svaret. Det gjelder også når jeg har *opplyst* brukeren om
at kontrollen ikke er ferdig; å si det er ikke å vente på det.

## Det som er lett å glemme

**En lukking varsler ikke kunden.** `notify_customer=True` gjør ingenting —
målt tre veier 22.09.2026. Skal kunden vite at saken er løst, må svaret sendes
med `reply_to_customer` **før** lukkingen.

**Lukk aldri i samme kjøring som første svar**, med mindre kunden alt har
bekreftet at problemet er borte. Et svar er ikke en løsning før kunden sier
det.

**Mottakeren kan `reply_to_customer` utlede.** Kontaktpersonens e-post er den
autoritative, kundekortet er reserven. Les `mottaker_kilde` og
`mottaker_utledet` i svaret uansett. Melder verktøyet konflikt — fordi den som
sist skrev inn er en annen enn kontaktpersonen — la saken stå. To plausible
mottakere er nettopp et tilfelle der et menneske må avgjøre.

## Rapporten

Avslutt med `autonomy_report()` og en oppsummering som sier hva du **ikke**
gjorde og hvilket kriterium som stoppet det. Det er den delen brukeren
egentlig trenger; det du fikk til ser hen i sakene.
