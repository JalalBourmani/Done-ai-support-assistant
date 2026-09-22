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

## Tre sperrer som ikke skal omgås

- Tak på 20 skrivehandlinger per kjøring. Nås det, stopp og rapporter. Ikke hev
  det.
- Ingen skriving til en sak som ikke er lest i samme kjøring.
- Alt loggføres, både utført og avvist.

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
