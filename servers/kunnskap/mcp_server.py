"""Kunnskaps-MCP: Confluence + Amendos offentlige hjelpesenter.

Erstatter notebooklm-mcp. To kilder, ulik tillit og ulik tilgang:

  * support.amendo.no  - offentlig WordPress, ingen legitimasjon, kundevendt.
  * Confluence         - internt, krever lesetoken, der prosedyrene skal bo.

DESIGNREGLER, alle tre kjopt med smerte i uke 38/2026:

1. ALDRI STILLE TOMT SVAR. Et sok som gir null treff sier det eksplisitt og
   gjentar hva som ble sokt paa. Grunnen: hjelpesenteret har 0 treff paa
   DonePay, AmendoGo, Adyen, BAX og iGive. Et tomt svar som ser ut som "ingen
   problemer" er verre enn en feilmelding - det var nettopp saan
   wp_woo_sync_log_activity lurte oss, der 713 594 rader alle var status 0.

2. ALDRI SAMMENDRAG UTEN KILDE. Hvert treff baerer tittel, URL og sist endret.
   Utkast som gaar til en regnskapsforer maa kunne etterproves av Jalal.

3. EN HTTP-FEIL ER EN FEIL. Nettverksfeil og 4xx/5xx returneres som feiltekst,
   aldri som en tom trefflist. Samme grunn som punkt 1.
"""

import base64
import html
import json
import os
import re
import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Kunnskap: Confluence + Amendo hjelpesenter")

# --- Konfigurasjon --------------------------------------------------------

DEFAULT_HELP_URL = "https://support.amendo.no"
DEFAULT_TIMEOUT = 30

# WordPress eksponerer flere innholdstyper. Hjelpesenteret har 110 dokumenter
# i 'docs', 36 i 'pages' og bare 4 i 'posts' - sokte vi bare i 'posts' ville
# vi oversett 97 % av innholdet. Rekkefolgen styrer visningen.
WP_TYPES = ("docs", "pages", "posts", "faq")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip().rstrip("/")


def help_url() -> str:
    return _env("HELPCENTER_URL", DEFAULT_HELP_URL)


def confluence_url() -> str:
    return _env("CONFLUENCE_URL")


def confluence_auth():
    """Basic auth for Confluence Cloud: e-post + API-token."""
    email = _env("CONFLUENCE_EMAIL")
    token = os.getenv("CONFLUENCE_TOKEN") or ""
    return (email, token.strip()) if email and token.strip() else None


def _timeout() -> int:
    raw = os.getenv("KUNNSKAP_TIMEOUT")
    try:
        v = int(raw) if raw else DEFAULT_TIMEOUT
        return v if v > 0 else DEFAULT_TIMEOUT
    except ValueError:
        return DEFAULT_TIMEOUT


# --- Hjelpere -------------------------------------------------------------

def _rens(raw: str, maks: int = 600) -> str:
    """HTML -> lesbar tekst. WordPress og Confluence returnerer begge markup."""
    if not raw:
        return ""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t[:maks] + ("…" if len(t) > maks else "")


def _utdrag(tekst: str, sporring: str, bredde: int = 320) -> str:
    """Klipper rundt forste treff paa et av sokeordene, ikke fra starten.

    Et utdrag fra artikkelens forste avsnitt sier nesten aldri hvorfor
    artikkelen traff. Det gjor et utdrag rundt sokeordet.
    """
    if not tekst:
        return ""
    for ord_ in sorted(sporring.split(), key=len, reverse=True):
        if len(ord_) < 3:
            continue
        m = re.search(re.escape(ord_), tekst, re.I)
        if m:
            start = max(0, m.start() - bredde // 3)
            bit = tekst[start:start + bredde]
            return ("…" if start else "") + bit.strip() + \
                   ("…" if start + bredde < len(tekst) else "")
    return tekst[:bredde].strip() + ("…" if len(tekst) > bredde else "")


def _hent(url: str, params=None, auth=None, hoder=None):
    """GET som returnerer (data, feiltekst). Nøyaktig én av dem er None."""
    try:
        r = requests.get(url, params=params, auth=auth,
                         timeout=_timeout(),
                         headers=hoder or {"Accept": "application/json"})
    except requests.RequestException as e:
        return None, "Nettverksfeil mot %s: %s" % (url, e)
    if r.status_code == 401:
        return None, ("401 Uautorisert mot %s. Token mangler eller er "
                      "utlopt." % url)
    if r.status_code == 403:
        return None, "403 Ingen tilgang til %s." % url
    if r.status_code >= 400:
        return None, "HTTP %d fra %s: %s" % (r.status_code, url, r.text[:200])
    try:
        return r.json(), None
    except ValueError:
        return None, "Svaret fra %s var ikke JSON (%d tegn)." % (url,
                                                                 len(r.text))


def _wp(sti: str, params=None):
    """WordPress REST via ?rest_route=. Pene URL-er kan vaere brukket paa
    LiteSpeed-oppsett - ?rest_route= virker uansett omskrivingsregler."""
    p = dict(params or {})
    p["rest_route"] = "/wp/v2/" + sti
    return _hent(help_url() + "/", p)


# --- Hjelpesenteret -------------------------------------------------------

@mcp.tool()
def sok_hjelpesenter(sporring: str, maks: int = 8) -> str:
    """Søker i Amendos offentlige hjelpesenter (support.amendo.no).

    Dekker alle innholdstyper: docs, sider, innlegg og FAQ. Bruk dette for å
    finne en artikkel du kan lenke til i et svar til kunde.

    Args:
        sporring: Søketekst, f.eks. "dagsoppgjør" eller "PowerOffice GO".
        maks: Maks antall treff (1-25).
    """
    if not sporring.strip():
        return "Tom søkestreng."
    # NB: 'maks or 8' ville gjort maks=0 til 8 - et eksplisitt tall byttet
    # stille ut med standardverdien. Klem i stedet til lovlig omraade.
    maks = max(1, min(int(8 if maks is None else maks), 25))

    treff, feil, sokt = [], [], []
    for t in WP_TYPES:
        sokt.append(t)
        data, f = _wp(t, {"search": sporring, "per_page": maks,
                          "orderby": "modified", "order": "desc"})
        if f:
            # En type som ikke finnes (404) er ikke en feil - FAQ mangler
            # rest_base paa noen oppsett. Alt annet er verdt aa vise.
            if "HTTP 404" not in f:
                feil.append("%s: %s" % (t, f))
            continue
        for x in data or []:
            raw = (x.get("content") or {}).get("rendered", "") or \
                  (x.get("excerpt") or {}).get("rendered", "")
            treff.append({
                "type": t,
                "tittel": _rens((x.get("title") or {}).get("rendered", ""), 160),
                "url": x.get("link") or "",
                "endret": (x.get("modified") or "")[:10],
                "utdrag": _utdrag(_rens(raw, 4000), sporring),
            })

    ut = ["Hjelpesenter: %s" % help_url(),
          "Søk: %r  (typer: %s)" % (sporring, ", ".join(sokt))]
    if feil:
        ut.append("ADVARSEL - deler av søket feilet, treffliste er ufullstendig:")
        ut += ["  " + e for e in feil]
    if not treff:
        # Eksplisitt, ikke tomt. Se designregel 1.
        ut.append("")
        ut.append("0 TREFF på %r i hjelpesenteret." % sporring)
        ut.append("Det betyr at emnet ikke er dokumentert der - ikke at "
                  "problemet ikke finnes. Kjenner du emnet, er dette et hull "
                  "verdt å melde.")
        return "\n".join(ut)

    ut.append("%d treff:" % len(treff[:maks * 2]))
    for i, x in enumerate(treff[:maks * 2], 1):
        ut.append("")
        ut.append("%d. %s   [%s, endret %s]" % (i, x["tittel"], x["type"],
                                                x["endret"] or "ukjent"))
        ut.append("   %s" % x["url"])
        if x["utdrag"]:
            ut.append("   %s" % x["utdrag"])
    return "\n".join(ut)


@mcp.tool()
def hent_hjelpeartikkel(url: str) -> str:
    """Henter hele teksten i én artikkel fra hjelpesenteret.

    Args:
        url: Full URL til artikkelen, slik sok_hjelpesenter oppgir den.
    """
    if not url.strip():
        return "Tom URL."
    base = help_url()
    if not url.startswith(base):
        return ("URL-en hører ikke til %s. Dette verktøyet leser bare "
                "hjelpesenteret." % base)

    # WordPress har ingen "hent etter URL", saa vi slaar opp slug-en.
    slug = [s for s in url.rstrip("/").split("/") if s][-1]
    for t in WP_TYPES:
        data, f = _wp(t, {"slug": slug, "per_page": 1})
        if f or not data:
            continue
        x = data[0]
        tekst = _rens((x.get("content") or {}).get("rendered", ""), 20000)
        return "\n".join([
            "%s" % _rens((x.get("title") or {}).get("rendered", ""), 200),
            "Kilde: %s" % (x.get("link") or url),
            "Type: %s   Sist endret: %s" % (t, (x.get("modified") or "")[:10]),
            "-" * 70,
            tekst or "(artikkelen har ingen tekst)",
        ])
    return ("Fant ingen artikkel med slug %r i %s. Sjekk URL-en, eller bruk "
            "sok_hjelpesenter for å finne den." % (slug, ", ".join(WP_TYPES)))


# --- Confluence -----------------------------------------------------------

def cloud_id(base: str):
    """Henter Atlassians cloudId. Offentlig endepunkt, ingen legitimasjon.

    Scoped tokens adresserer ikke nettstedet direkte, men gaar via
    api.atlassian.com/ex/confluence/<cloudId>. Id-en kan forhaandssettes i
    config.env for aa spare et kall.
    """
    forhaands = _env("CONFLUENCE_CLOUD_ID")
    if forhaands:
        return forhaands, None
    data, f = _hent(base + "/_edge/tenant_info")
    if f:
        return None, "Kunne ikke hente cloudId fra %s: %s" % (base, f)
    cid = (data or {}).get("cloudId")
    return (cid, None) if cid else (None, "Svaret fra _edge/tenant_info "
                                          "manglet cloudId.")


# Atlassian har to token-typer med ULIKE auth-skjema, og feil skjema gir 401
# paa alt - ogsaa endepunkter tokenet har omfang til. Derfor prover vi begge
# og husker hvilket som virket.
#
#   scoped  : Authorization: Bearer <token>
#             https://api.atlassian.com/ex/confluence/<cloudId>
#   klassisk: Authorization: Basic base64(epost:token)
#             https://<firma>.atlassian.net
_klient_cache = None


def _confluence_klient(tving_ny: bool = False):
    """(base, headers, modus) eller (None, None, feiltekst)."""
    global _klient_cache
    if _klient_cache and not tving_ny:
        return _klient_cache

    sted = confluence_url()
    if not sted:
        return None, None, ("CONFLUENCE_URL er ikke satt i config.env. "
                            "Forventet form: https://<firma>.atlassian.net")
    auth = confluence_auth()
    if not auth:
        return None, None, ("Confluence-legitimasjon mangler. Kjør "
                            "scripts\\configure-confluence.ps1 for å legge "
                            "inn e-post + API-token.")
    epost, token = auth

    forsok, feil = [], []

    cid, f = cloud_id(sted)
    if cid:
        forsok.append((
            "scoped (Bearer via api.atlassian.com)",
            "https://api.atlassian.com/ex/confluence/" + cid,
            {"Authorization": "Bearer " + token, "Accept": "application/json"},
        ))
    else:
        feil.append(f)

    par = base64.b64encode(("%s:%s" % (epost, token)).encode()).decode()
    forsok.append((
        "klassisk (Basic mot nettstedet)",
        sted,
        {"Authorization": "Basic " + par, "Accept": "application/json"},
    ))

    for modus, base, hoder in forsok:
        try:
            r = requests.get(base + "/wiki/api/v2/spaces",
                             params={"limit": 1}, headers=hoder,
                             timeout=_timeout())
        except requests.RequestException as e:
            feil.append("%s: nettverksfeil %s" % (modus, e))
            continue
        if r.status_code < 400:
            _klient_cache = (base, hoder, modus)
            return _klient_cache
        feil.append("%s: HTTP %d" % (modus, r.status_code))

    return None, None, (
        "Ingen av auth-skjemaene ble godtatt.\n  "
        + "\n  ".join(feil)
        + "\n\nTolkning:"
          "\n  401/404 paa begge  - feil e-post eller token, eller tokenet er"
          " ikke aktivert ennaa (Atlassian bruker opptil ett minutt, og "
          "svarer 404 framfor 401 paa v2 naar auth ikke godtas)."
          "\n  403               - tokenet er gyldig, men mangler omfang."
          "\n  Bare ett skjema OK - det er normalt; serveren bruker det som"
          " virket.")


@mcp.tool()
def sok_confluence(sporring: str, rom: str = "", maks: int = 8) -> str:
    """Søker i Confluence med CQL.

    Args:
        sporring: Fritekst, f.eks. "BAX gavekort".
        rom: Valgfri romnøkkel for å begrense søket, f.eks. "SUPPORT".
        maks: Maks antall treff (1-25).
    """
    base, hoder, modus = _confluence_klient()
    if base is None:
        return modus
    if not sporring.strip():
        return "Tom søkestreng."
    # NB: 'maks or 8' ville gjort maks=0 til 8 - et eksplisitt tall byttet
    # stille ut med standardverdien. Klem i stedet til lovlig omraade.
    maks = max(1, min(int(8 if maks is None else maks), 25))

    # Et romnavn som ikke finnes gir ellers "0 treff", og da leser man det som
    # "emnet er udokumentert" naar sannheten er "du skrev rommet feil". Det er
    # samme tvetydighet verktoyet skal fjerne, saa romnokkelen valideres.
    rom = rom.strip()
    if rom:
        nokler, f = _romnokler()
        if f:
            return "Kunne ikke sjekke romnøkkelen mot Confluence.\n%s" % f
        if rom.lower() not in {k.lower() for k in nokler}:
            team = sorted(k for k in nokler if not k.startswith("~"))
            return ("Rommet %r finnes ikke i Confluence.\n"
                    "Dette er IKKE et null-treff - søket ble aldri kjørt.\n\n"
                    "Tilgjengelige fellesrom: %s\n"
                    "(i tillegg finnes %d personlige rom)"
                    % (rom, ", ".join(team) or "(ingen)",
                       len(nokler) - len(team)))

    # text~ soker i brodteksten. Anforselstegn maa escapes, ellers brekker CQL.
    trygg = sporring.replace('"', '\\"')
    cql = 'text ~ "%s"' % trygg
    if rom:
        cql = 'space = "%s" AND %s' % (rom.replace('"', ""), cql)
    cql += " ORDER BY lastmodified DESC"

    data, f = _hent(base + "/wiki/rest/api/search",
                    {"cql": cql, "limit": maks, "expand": "content.version"},
                    hoder=hoder)
    if f:
        return ("Søk i Confluence feilet (%s).\nCQL: %s\n%s\n\n"
                "Virker rom-oppslaget men ikke søket, mangler tokenet "
                "omfanget 'search:confluence'." % (modus, cql, f))

    res = (data or {}).get("results") or []
    ut = ["Confluence: %s  [%s]" % (confluence_url(), modus),
          "CQL: %s" % cql]
    if not res:
        ut.append("")
        ut.append("0 TREFF på %r%s." % (sporring,
                                        " i rom %s" % rom if rom else ""))
        ut.append("Emnet er ikke dokumentert i Confluence - det er ikke det "
                  "samme som at det ikke finnes. Er dette noe vi kan, er "
                  "hullet verdt å melde.")
        return "\n".join(ut)

    ut.append("%d treff:" % len(res))
    for i, x in enumerate(res, 1):
        c = x.get("content") or {}
        lenke = x.get("url") or ""
        ut.append("")
        ut.append("%d. %s   [%s]" % (i, x.get("title") or c.get("title") or "?",
                                     c.get("type") or x.get("entityType") or "?"))
        if lenke:
            ut.append("   %s/wiki%s" % (confluence_url(), lenke))
        if c.get("id"):
            ut.append("   side-id: %s" % c["id"])
        if x.get("lastModified"):
            ut.append("   sist endret: %s" % str(x["lastModified"])[:10])
        if x.get("excerpt"):
            ut.append("   %s" % _rens(x["excerpt"], 300))
    return "\n".join(ut)


@mcp.tool()
def hent_confluence_side(side_id: str) -> str:
    """Henter hele innholdet i én Confluence-side.

    Args:
        side_id: Side-id, slik sok_confluence oppgir den.
    """
    base, hoder, modus = _confluence_klient()
    if base is None:
        return modus
    sid = str(side_id).strip()
    if not sid.isdigit():
        return "side_id må være et tall. Fikk %r." % side_id

    data, f = _hent("%s/wiki/api/v2/pages/%s" % (base, sid),
                    {"body-format": "storage"}, hoder=hoder)
    if f:
        return "Kunne ikke hente side %s.\n%s" % (sid, f)

    body = ((data or {}).get("body") or {}).get("storage", {}).get("value", "")
    return "\n".join([
        str((data or {}).get("title") or "?"),
        "Kilde: %s/wiki/spaces/%s/pages/%s" % (
            confluence_url(), (data or {}).get("spaceId", ""), sid),
        "Versjon: %s" % (((data or {}).get("version") or {}).get("number", "?")),
        "-" * 70,
        _rens(body, 20000) or "(siden har ingen tekst)",
    ])


_rom_cache = None


def _romnokler():
    """Alle romnokler, paginert. (nokler, None) eller (None, feiltekst).

    Confluence gir 25 rom per side som standard, og sider nummer to og utover
    naas bare via _links.next. Uten paginering ville valideringen avvist
    gyldige rom som "finnes ikke" - stille, og med full selvtillit.
    """
    global _rom_cache
    if _rom_cache is not None:
        return _rom_cache, None

    base, hoder, modus = _confluence_klient()
    if base is None:
        return None, modus

    nokler, kursor, runder = [], None, 0
    while runder < 40:
        runder += 1
        p = {"limit": 100}
        if kursor:
            p["cursor"] = kursor
        d, f = _hent(base + "/wiki/api/v2/spaces", p, hoder=hoder)
        if f:
            return None, f
        nokler += [str(r.get("key")) for r in ((d or {}).get("results") or [])
                   if r.get("key")]
        nxt = ((d or {}).get("_links") or {}).get("next") or ""
        m = re.search(r"[?&]cursor=([^&]+)", nxt)
        if not m:
            break
        kursor = m.group(1)

    _rom_cache = nokler
    return nokler, None


# --- Status ---------------------------------------------------------------

@mcp.tool()
def kunnskapsstatus() -> str:
    """Sjekker at begge kunnskapskildene svarer, og hvor store de er.

    Kjør denne før du stoler på et null-treff. Et tomt søk kan betyde at
    emnet mangler - eller at kilden er nede. Dette skiller de to.
    """
    ut = []

    ut.append("HJELPESENTER  %s" % help_url())
    tot = {}
    for t in WP_TYPES:
        try:
            r = requests.get(help_url() + "/",
                             params={"rest_route": "/wp/v2/" + t,
                                     "per_page": 1},
                             timeout=_timeout())
            tot[t] = r.headers.get("x-wp-total", "?") if r.ok else \
                "HTTP %d" % r.status_code
        except requests.RequestException as e:
            tot[t] = "nettverksfeil: %s" % str(e)[:60]
    for t in WP_TYPES:
        ut.append("  %-8s %s dokumenter" % (t, tot.get(t, "?")))

    nyest, f = _wp("docs", {"per_page": 1, "orderby": "modified",
                            "order": "desc"})
    if not f and nyest:
        ut.append("  sist endret: %s (%s)"
                  % ((nyest[0].get("modified") or "")[:10],
                     _rens((nyest[0].get("title") or {}).get("rendered", ""), 60)))
    elif f:
        ut.append("  ADVARSEL: %s" % f)

    ut.append("")
    base, hoder, modus = _confluence_klient(tving_ny=True)
    if base is None:
        ut.append("CONFLUENCE    ikke tilgjengelig")
        for linje in str(modus).splitlines():
            ut.append("  %s" % linje)
    else:
        ut.append("CONFLUENCE    %s" % confluence_url())
        ut.append("  auth: %s" % modus)
        data, f = _hent(base + "/wiki/api/v2/spaces", {"limit": 25}, hoder=hoder)
        if f:
            ut.append("  FEIL: %s" % f)
        else:
            rom = (data or {}).get("results") or []
            ut.append("  %d rom tilgjengelig%s"
                      % (len(rom), ":" if rom else ""))
            for r in rom[:25]:
                ut.append("    %-12s %s" % (r.get("key", "?"),
                                            r.get("name", "")))
    return "\n".join(ut)


if __name__ == "__main__":
    mcp.run()
