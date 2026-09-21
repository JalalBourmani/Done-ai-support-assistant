# Tre modus, ikke to

Verktoyene er de samme i alle tre. Det som skiller er hvor langt handlingene
rekker, og hvem som leser dem for kunden gjor det.

| Modus | Styres av | Autonominivaa | Ender i |
|---|---|---|---|
| **Planlagt ko**, uovervaket | `auto-xsale-saksassistent.md` | irrelevant — se under | filer paa disk |
| **Samtale**, utkastmodus | `CLAUDE.md` | `les` eller `kommenter` | filer paa disk |
| **Samtale**, delegert | `auto-xsale-delegert.md` | `svar` eller `full` | handlinger i XSALE |

Det er bare to promptfiler her, og det er med vilje. `auto-xsale-saksassistent.md`
lastes **kun** av `scripts\run-auto-xsale.ps1`; i en samtale laster ingenting den.
Utkastmodus trenger ingen egen prompt fordi reglene alt staar i `CLAUDE.md` — en
tredje fil ville duplisert den, og duplikater divergerer.

## Planlagt ko

`scripts\run-auto-xsale.ps1`, eventuelt via `register-scheduled-task.ps1`.

**Autonominivaaet gjelder ikke her.** Kjoringen har en hviteliste som bare
inneholder lesende verktoy, og `$forbidden` stopper kjoringen for den starter
hvis noen legger inn et skrivende. Det er med vilje: en uovervaket kjoring som
kan svare kunder er en annen risiko enn en som skriver utkast til disk.

Skal koen en dag kunne handle, er det en egen beslutning som krever at
hvitelisten endres — ikke noe et hevet autonominivaa gjor av seg selv.

## Utkastmodus

Slik vi har jobbet hele veien. Jeg undersoker, kommenterer internt, og skriver
`troubleshooting.md` og `draft_reply.md`. Du leser i frontenden og sender selv.

**Ingen prompt lastes.** `CLAUDE.md` i arbeidsmappen styrer dette — den skrives
av `install.ps1` fra `templates\CLAUDE.md.template`. Standardnivaaet er `les`,
saa utkastmodus er det du faar uten aa gjore noe.

Du kan gjerne be meg ta en konkret sak, eller se paa koen. Forskjellen fra den
planlagte koen er at du er til stede: jeg kan spore, og vi kan ta opp en sak vi
alt har behandlet uten at det bryter noen regel.

## Delegert modus

For helger og ferie. Krever at du hever nivaaet eksplisitt:

```
set_autonomy("svar", "helgevakt 27.-28.09")
```

`svar` lar meg svare kunder. `full` lar meg ogsaa lukke saker. Nivaaet gjelder
bare den kjoringen — sett `XSALE_AUTONOMY` i `config.env` for aa gjore det
varig.

Prompten `auto-xsale-delegert.md` har seks kriterier en sak maa oppfylle for
den loses alene, og en liste over saker som aldri loses alene uansett niva.
Les den for du hever nivaaet forste gang, saa du vet hva du delegerer.

Rapporten kommer fra `autonomy_report()` og
`${AUTO_XSALE_ROOT}/_delegert-rapport.md`. Den forteller ogsaa hva som IKKE ble
gjort, og hvilket kriterium som stoppet det.

## Ikke avklart enda

`notify_customer=True` paa `set_case_status` er aldri testet. Vi har bare kjort
`sendEmail=false`, saa ingen vet hva kunden faktisk mottar naar en sak lukkes
med varsling. Avklar det for delegert modus brukes paa en reell sak.
