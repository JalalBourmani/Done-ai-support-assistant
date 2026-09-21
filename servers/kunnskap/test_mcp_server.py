"""Tester for kunnskap-mcp-server.

Kjor fra kit-rotens venv:

    .venv\\Scripts\\python.exe -m pytest kunnskap-mcp-server -q

De fleste testene er offline og trenger ingen legitimasjon. De som treffer
nettet hopper av seg selv naar CONFLUENCE_TOKEN mangler, saa suiten kan kjores
paa en maskin uten oppsett.

HOVEDREGELEN SOM TESTES: ingen verktoy skal returnere tomt eller kaste. Et
udokumentert emne, en tastefeil i romnavnet og en nede kilde skal gi TRE ulike
og tydelige svar. Grunnen staar i modulens docstring.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_server as K  # noqa: E402


har_token = bool(os.getenv("CONFLUENCE_TOKEN"))
krever_token = pytest.mark.skipif(
    not har_token, reason="CONFLUENCE_TOKEN mangler - hopper over nettverkstest")


# --- Tekstbehandling ------------------------------------------------------

def test_rens_fjerner_markup_og_entiteter():
    assert K._rens("<p>Hei &amp; h&oslash;r</p>") == "Hei & hør"


def test_rens_dropper_script_og_style():
    ut = K._rens("<style>p{color:red}</style><p>Innhold</p><script>x()</script>")
    assert "color" not in ut and "x()" not in ut
    assert "Innhold" in ut


def test_rens_taaler_tomt():
    assert K._rens("") == ""
    assert K._rens(None) == ""


def test_utdrag_klipper_rundt_treffet_ikke_fra_starten():
    tekst = ("innledning " * 40) + "BAX-nummeret tildeles av NETS " + ("hale " * 40)
    ut = K._utdrag(tekst, "BAX", bredde=120)
    assert "BAX" in ut, "utdraget skal vise sokeordet, ellers ser man ikke hvorfor det traff"


def test_utdrag_faller_tilbake_til_starten_uten_treff():
    ut = K._utdrag("noe helt annet", "finnesikke", bredde=50)
    assert ut.startswith("noe helt annet")


# --- Konfigurasjon --------------------------------------------------------

def test_help_url_har_fornuftig_standard(monkeypatch):
    monkeypatch.delenv("HELPCENTER_URL", raising=False)
    assert K.help_url() == "https://support.amendo.no"


def test_url_far_ikke_etterslepende_skraastrek(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_URL", "https://x.atlassian.net/")
    assert K.confluence_url() == "https://x.atlassian.net"


def test_auth_krever_bade_epost_og_token(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_EMAIL", "a@b.no")
    monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)
    assert K.confluence_auth() is None
    monkeypatch.setenv("CONFLUENCE_TOKEN", "  ")
    assert K.confluence_auth() is None, "blanke tegn er ikke et token"


def test_timeout_faller_tilbake_paa_ugyldig_verdi(monkeypatch):
    monkeypatch.setenv("KUNNSKAP_TIMEOUT", "tull")
    assert K._timeout() == K.DEFAULT_TIMEOUT
    monkeypatch.setenv("KUNNSKAP_TIMEOUT", "-4")
    assert K._timeout() == K.DEFAULT_TIMEOUT


# --- Verktoyene skal aldri svare tomt ------------------------------------

def test_tom_sporring_gir_beskjed():
    assert "Tom" in K.sok_hjelpesenter("   ")
    assert "Tom" in K.sok_confluence("   ")


@pytest.mark.parametrize("sid", ["", "tull", "-5", "12.5", "1e5"])
def test_ugyldig_side_id_avvises_for_nettkall(sid):
    ut = K.hent_confluence_side(sid)
    assert "må være et tall" in ut


def test_hjelpeartikkel_godtar_bare_hjelpesenteret():
    ut = K.hent_hjelpeartikkel("https://evil.example/docs/x")
    assert "hører ikke til" in ut, "verktoyet skal ikke kunne omdirigeres til andre nettsteder"


def test_hjelpeartikkel_tom_url():
    assert "Tom URL" in K.hent_hjelpeartikkel("")


# --- Romvalidering --------------------------------------------------------

def test_ukjent_rom_skiller_seg_fra_null_treff(monkeypatch):
    """Tastefeil i romnavnet skal IKKE se ut som et udokumentert emne."""
    monkeypatch.setattr(K, "_confluence_klient",
                        lambda *a, **k: ("https://base", {}, "test"))
    monkeypatch.setattr(K, "_romnokler",
                        lambda: (["Support", "TEAM", "~personlig"], None))
    ut = K.sok_confluence("gavekort", rom="Suport")
    assert "finnes ikke" in ut
    assert "IKKE et null-treff" in ut
    assert "Support" in ut and "TEAM" in ut, "skal vise hvilke rom som finnes"
    assert "~personlig" not in ut, "personlige rom er stoy i en slik liste"


def test_rom_er_ikke_kasussensitivt(monkeypatch):
    monkeypatch.setattr(K, "_confluence_klient",
                        lambda *a, **k: ("https://base", {}, "test"))
    monkeypatch.setattr(K, "_romnokler", lambda: (["Support"], None))
    monkeypatch.setattr(K, "_hent", lambda *a, **k: ({"results": []}, None))
    ut = K.sok_confluence("x", rom="SUPPORT")
    assert "finnes ikke" not in ut


def test_romoppslag_som_feiler_gir_feil_ikke_null_treff(monkeypatch):
    monkeypatch.setattr(K, "_confluence_klient",
                        lambda *a, **k: ("https://base", {}, "test"))
    monkeypatch.setattr(K, "_romnokler", lambda: (None, "503 fra Confluence"))
    ut = K.sok_confluence("x", rom="Support")
    assert "503" in ut and "0 TREFF" not in ut


def test_null_treff_sier_det_eksplisitt(monkeypatch):
    monkeypatch.setattr(K, "_confluence_klient",
                        lambda *a, **k: ("https://base", {}, "test"))
    monkeypatch.setattr(K, "_hent", lambda *a, **k: ({"results": []}, None))
    ut = K.sok_confluence("ESPOS")
    assert "0 TREFF" in ut
    assert "ikke det samme som at det ikke finnes" in ut


# --- CQL -----------------------------------------------------------------

def test_anforselstegn_escapes_i_cql(monkeypatch):
    fanget = {}

    def fake(url, params=None, auth=None, hoder=None):
        fanget["cql"] = (params or {}).get("cql", "")
        return {"results": []}, None

    monkeypatch.setattr(K, "_confluence_klient",
                        lambda *a, **k: ("https://base", {}, "test"))
    monkeypatch.setattr(K, "_hent", fake)
    K.sok_confluence('a" OR type="page')
    assert '\\"' in fanget["cql"], "uescapede anforselstegn brekker eller utvider soket"


@pytest.mark.parametrize("inn,ventet", [(0, 1), (-3, 1), (999, 25), (8, 8)])
def test_maks_klemmes_til_lovlig_omraade(monkeypatch, inn, ventet):
    fanget = {}

    def fake(url, params=None, auth=None, hoder=None):
        fanget["limit"] = (params or {}).get("limit")
        return {"results": []}, None

    monkeypatch.setattr(K, "_confluence_klient",
                        lambda *a, **k: ("https://base", {}, "test"))
    monkeypatch.setattr(K, "_hent", fake)
    K.sok_confluence("x", maks=inn)
    assert fanget["limit"] == ventet


# --- Feilhaandtering i _hent ---------------------------------------------

class _Svar:
    def __init__(self, kode, tekst='{"ok":1}'):
        self.status_code = kode
        self.text = tekst

    def json(self):
        import json
        return json.loads(self.text)


@pytest.mark.parametrize("kode,nokkelord", [
    (401, "401"), (403, "403"), (500, "500"),
])
def test_hent_returnerer_feiltekst_ikke_tom_liste(monkeypatch, kode, nokkelord):
    monkeypatch.setattr(K.requests, "get", lambda *a, **k: _Svar(kode, "aiai"))
    data, f = K._hent("https://x")
    assert data is None and nokkelord in f


def test_hent_melder_naar_svaret_ikke_er_json(monkeypatch):
    monkeypatch.setattr(K.requests, "get",
                        lambda *a, **k: _Svar(200, "<html>ikke json</html>"))
    data, f = K._hent("https://x")
    assert data is None and "ikke JSON" in f


def test_hent_melder_nettverksfeil(monkeypatch):
    def boom(*a, **k):
        raise K.requests.RequestException("tidsavbrudd")

    monkeypatch.setattr(K.requests, "get", boom)
    data, f = K._hent("https://x")
    assert data is None and "Nettverksfeil" in f


# --- Nettverkstester (hopper av uten legitimasjon) -----------------------

@krever_token
def test_status_naar_begge_kilder():
    ut = K.kunnskapsstatus()
    assert "HJELPESENTER" in ut and "CONFLUENCE" in ut
    assert "dokumenter" in ut
    assert "ikke tilgjengelig" not in ut, "Confluence skal svare naar token finnes"


@krever_token
def test_romnokler_pagineres():
    nokler, f = K._romnokler()
    assert f is None
    assert len(nokler) > 25, ("faerre enn 26 rom betyr at pagineringen ikke "
                              "virker - Confluence gir 25 per side")


@krever_token
def test_sok_finner_kjent_side():
    ut = K.sok_confluence("iGive", rom="Support", maks=3)
    assert "Gavekort Adyen" in ut
    assert "side-id:" in ut, "treff uten side-id kan ikke hentes etterpaa"
    assert "tellix.atlassian.net/wiki" in ut, "treff uten lenke kan ikke etterproves"


@krever_token
def test_hent_side_gir_kilde_og_versjon():
    ut = K.hent_confluence_side("192250092")
    assert "Kilde:" in ut and "Versjon:" in ut


def test_hjelpesenter_svarer():
    """Offentlig kilde - denne skal virke uten legitimasjon."""
    ut = K.sok_hjelpesenter("dagsoppgjør", maks=2)
    assert "support.amendo.no" in ut
    assert "0 TREFF" not in ut, "dagsoppgjor er dokumentert - null treff betyr brutt kilde"
