# Eksempler

## `saksmappe-eksempel/`

Slik ser en saksmappe ut når saksassistenten har behandlet en sak. **Alt innholdet er oppdiktet** —
kunde, saksnummer, serienumre og datoer finnes ikke. Ingen reelle kundedata i dette repoet.

| Fil | Hva den er |
|---|---|
| `case_raw.json` | Metadata fra XSALE. Kun de sju feltene saksoversikten leser — aldri hele rådataen, siden kundenotater i XSALE ofte inneholder passord og PIN-koder |
| `troubleshooting.md` | Analysen. Merk inndelingen: bekreftede funn, sannsynlig vurdering, og det du må kontrollere manuelt |
| `draft_reply.md` | Svarutkast, klart til gjennomgang. **Aldri sendt** — assistenten sender ikke e-post |

### Det som er verdt å legge merke til

**Skillet mellom bekreftet og antatt.** Analysen sier hva som er lest ut av databasen, hva som er en
sannsynlig forklaring, og hva den ikke kan vite. Det skillet er hele poenget — du skal kunne stole på
den første kategorien uten å etterprøve alt.

**Kontroll av datamengden.** Eksempelet nevner eksplisitt at spørringen ga 14 rader og at `COUNT(*)`
ga 14. Et avkuttet resultat ser identisk ut med et fullstendig, så antallet må avstemmes.

**Utkastet svarer på det kunden spurte om,** og stiller ett konkret spørsmål tilbake i stedet for å
gjette. Det er raskere enn å sende noe som må korrigeres.

**Ingenting er sendt eller lukket.** Assistenten skriver til disk. Alt som går ut, går ut fra deg.

---

## Dine egne saksmapper

De ligger **utenfor** dette repoet, i mappen du valgte under installasjonen — standard
`%USERPROFILE%\Documents\Auto-XSALE`.

Det er bevisst. Kundedata skal ikke kunne havne i Git ved et uhell. Ikke flytt dem hit inn.
