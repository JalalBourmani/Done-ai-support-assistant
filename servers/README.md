# MCP-serverne

| Mappe | Server | Startes med |
|---|---|---|
| `xsale/` | XSALE CRM — saker, kommunikasjon, kundekort, ordre. Kan skrive | `scripts\run-mcp.ps1 -Server xsale` |
| `mysql/` | ProTouch-databasen via phpMyAdmin. Skrivebeskyttet | `scripts\run-mcp.ps1 -Server mysql` |

Hver mappe har sin egen README med verktøyliste, funn og forbehold. Les
`xsale/README.md` før du bruker skriveverktøyene — autonominivåene og
mottakersperren er beskrevet der.

## Kjøring av testene

**Kjør én server av gangen:**

```powershell
..\..\.venv\Scripts\python.exe -m pytest servers\xsale\test_regresjon.py
..\..\.venv\Scripts\python.exe -m pytest servers\mysql\test_mcp_server.py
```

**`pytest servers/` virker ikke**, og feilmeldingen peker et helt annet sted enn
årsaken:

```
ImportError: cannot import name 'parse_truncated_columns' from 'mcp_server'
(.../servers/xsale/mcp_server.py)
```

Begge serverne har en modul som heter `mcp_server`. I én pytest-kjøring havner
den som lastes først i `sys.modules`, og den andre mappas tester importerer da
feil modul. Avhengig av rekkefølgen får du enten innsamlingsfeil eller 71
oppsettsfeil som ser ut som noe annet.

Det lar seg ikke løse med en `conftest.py`: pytest importerer alle
conftest-filer **før** testmodulene, så kode på modulnivå der kjører for tidlig,
mens en autouse-fixture kjører **etter** testmodulenes toppnivå-importer og
dermed for sent. Målt 21.09.2026 gjennom fire forsøk.

Den varige løsningen er å gi modulene ulike navn eller gjøre mappene til
pakker, og å endre importene i begge testfilene. Det er ikke gjort, fordi det
rører kode som virker. Inntil da: kjør én server av gangen.

`xsale/test_smoke.py` og `xsale/test_tools.py` snakker med levende XSALE og
krever legitimasjon. `xsale/test_regresjon.py` og `mysql/test_mcp_server.py`
kjører uten nett.

## Kontroll av at verktøyene faktisk serveres

```powershell
..\..\.venv\Scripts\python.exe servers\xsale\sjekk_servert_katalog.py
```

Starter en ekte serverprosess og teller verktøyene den svarer med over
`tools/list`. Det er ikke det samme som å importere modulen: 21.09.2026 lå fire
verktøy under `mcp.run()` i fila, så dekoratorene aldri kjørte, og katalogen
hadde 23 av 27 — mens et `import` viste alle 27, fordi `__name__` ikke er
`"__main__"` ved import og `mcp.run()` derfor hoppes over.
