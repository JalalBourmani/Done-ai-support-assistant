# Svarutkast — sak 41234, NORDVIK SPORT AS

> **Oppdiktet eksempel.** Viser formen på et svarutkast fra saksassistenten.
>
> **Ikke sendt.** Assistenten sender aldri e-post — den skriver utkast du går gjennom og sender selv.
>
> **Fyll inn før du sender:** `[NAVN]` på kontaktpersonen, og avklar punkt 3 under
> «Må kontrolleres manuelt» i `troubleshooting.md` — hvem som administrerer nettverket avgjør om vi
> gjør endringen eller ber kunden om det.

---

## E-post

**Emne:** Sak 41234 — avbrudd mellom kasse og terminal

Hei [NAVN],

Takk for at du meldte inn dette. Jeg har gått gjennom loggene, og jeg tror vi har funnet årsaken.

Terminalen deres har byttet IP-adresse tre ganger på fire dager. Det skjer fordi kassen får en ny
adresse fra ruteren med jevne mellomrom, mens terminalen fortsatt peker på den forrige. Da mister de
kontakten i under et minutt, før terminalen finner den nye adressen selv.

Jeg vil samtidig berolige deg på ett punkt: jeg har sjekket alle 14 avbruddene i loggen, og ingen av
dem faller sammen med et salg. Ingen transaksjoner har feilet, og ingen kunder er belastet feil.

Løsningen er å gi kassen en fast adresse i ruteren i stedet for at den tildeles på nytt. Det tar noen
minutter, og etter det skal avbruddene forsvinne helt — ikke bare bli sjeldnere.

Ett spørsmål jeg trenger svar på: er det dere som styrer nettverket i butikken, eller har dere en
ekstern leverandør på det? Er det oss som kan gjøre endringen, ordner jeg det. Er det en leverandør,
sender jeg deg det de trenger å vite, så slipper du å formidle det videre selv.

Terminalen er forøvrig 11 måneder gammel og har ingen feilkoder, så det er ikke noe galt med
maskinvaren.

Med vennlig hilsen
[DITT NAVN]
