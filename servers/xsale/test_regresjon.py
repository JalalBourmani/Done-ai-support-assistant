# -*- coding: utf-8 -*-
"""Regresjonstester for logikken som ble lagt til 21.09.2026.

Alt her kjorer uten nett. De eksisterende testene (test_smoke, test_tools)
snakker med XSALE og tar over et minutt; disse skal kunne kjores pa hver
endring. Hver test svarer til en konkret feil jeg har gjort.
"""

import ast
import io
import json
import os
import sys

import re

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_server as X  # noqa: E402


# --- Formatering: markdown -> XSALE-HTML ----------------------------------
#
# Bakgrunnen: forrige gang jeg kommenterte en sak kom teksten ut som en
# eneste blokk. XSALE-feltene er HTML, saa linjeskift ma vaere <br>.

def test_avsnitt_blir_br_ikke_blokk():
    ut = X._markdown_to_xsale_html("Linje en\nLinje to")
    assert "<br" in ut
    assert "Linje en" in ut and "Linje to" in ut


def test_fet_og_kode():
    ut = X._markdown_to_xsale_html("Det er **viktig** at `orgno` brukes")
    assert "<b>viktig</b>" in ut
    assert "<code>orgno</code>" in ut


def test_overskrift_liste_og_hr():
    ut = X._markdown_to_xsale_html(
        "## Funn\n\n- ett\n- to\n\n---\n\n1. forst\n2. sa")
    assert "<b>Funn</b>" in ut or "<h" in ut
    assert "<ul>" in ut and ut.count("<li>") >= 4
    assert "<ol>" in ut
    assert "<hr" in ut


def test_tabell_far_ramme():
    ut = X._markdown_to_xsale_html(
        "| Dato | Sum |\n|---|---|\n| 15.09 | 1 200,00 |")
    assert "<table" in ut and "border" in ut
    assert "1 200,00" in ut


def test_lenke():
    ut = X._markdown_to_xsale_html("Se [hjelpesenteret](https://support.amendo.no/)")
    assert '<a href="https://support.amendo.no/">hjelpesenteret</a>' in ut


def test_ganging_og_understrek_rores_ikke():
    """5 * 3 er ikke kursiv, og a_b_c er et feltnavn."""
    ut = X._markdown_to_xsale_html("5 * 3 = 15 og feltet er wp_woo_sync_log")
    assert "5 * 3 = 15" in ut
    assert "wp_woo_sync_log" in ut
    assert "<i>" not in ut and "<em>" not in ut


def test_html_escapes_for_konvertering():
    """Kundenavn som <Test & Co> skal ikke knekke markupen."""
    ut = X._markdown_to_xsale_html("Kunden <Test & Co> ringte")
    assert "&lt;Test &amp; Co&gt;" in ut


# --- Verifikasjon av at kommentaren faktisk landet ------------------------
#
# Feilen jeg fikset: verifikasjonen sammenlignet rå markdown mot HTML-en
# XSALE returnerer, og meldte derfor "ikke verifisert" pa kommentarer som
# hadde landet helt fint.

def test_signatur_ser_gjennom_markup():
    a = X._text_signature("<p>Hei <b>Jalal</b>,<br>alt er i orden</p>")
    b = X._text_signature("Hei Jalal, alt er i orden")
    assert a == b


def test_signatur_dekoder_entiteter():
    assert X._text_signature("Test &amp; Co") == X._text_signature("Test & Co")


def test_signatur_skiller_ulik_tekst():
    assert X._text_signature("saken er lost") != X._text_signature("saken er apen")


# --- Autonomigrensene ----------------------------------------------------

@pytest.fixture(autouse=True)
def nullstill_autonomi(tmp_path, monkeypatch):
    """Hver test starter pa 'les' med tom revisjonslogg."""
    monkeypatch.setattr(X, "_autonomy", None)
    monkeypatch.setattr(X, "_actions_done", 0)
    monkeypatch.setattr(X, "_actions_per_case", {})
    monkeypatch.setattr(X, "_cases_read", set())
    monkeypatch.setattr(X, "AUDIT_LOG", str(tmp_path / "audit.log"))
    monkeypatch.delenv("XSALE_AUTONOMY", raising=False)
    yield


def test_standard_er_les():
    assert X.autonomy() == "les"


def test_les_avviser_kommentar():
    X._mark_case_read(48423)
    svar = json.loads(X._krev_nivaa("add_case_comment", "kommenter", 48423))
    assert svar["utfort"] is False
    assert svar["arsak"] == "autonominivaa"
    assert "kommenter" in svar["kreves"]


def test_kommenter_tillater_kommentar_men_ikke_lukking():
    X.set_autonomy("kommenter", "test")
    X._mark_case_read(48423)
    assert X._krev_nivaa("add_case_comment", "kommenter", 48423) is None
    nekt = json.loads(X._krev_nivaa("close_case", "full", 48423))
    assert nekt["arsak"] == "autonominivaa"


def test_full_tillater_alt_pa_lest_sak():
    X.set_autonomy("full", "helgevakt")
    X._mark_case_read(48423)
    assert X._krev_nivaa("close_case", "full", 48423) is None


def test_ulest_sak_sperrer_selv_pa_full():
    """Sak 38306 ble lukket med fem uverifiserte punkter. Derfor denne."""
    X.set_autonomy("full", "test")
    svar = json.loads(X._krev_nivaa("close_case", "full", 99999))
    assert svar["arsak"] == "saken er ikke lest"


def test_handlingstaket_stopper_lokken():
    X.set_autonomy("full", "test")
    X._mark_case_read(48423)
    X._actions_done = X.MAX_AUTONOMOUS_ACTIONS
    svar = json.loads(X._krev_nivaa("add_case_comment", "kommenter", 48423))
    assert svar["arsak"] == "handlingstak"


def test_taket_per_sak_stopper_retting_av_retting():
    """Sak 48423 kostet 7 skrivehandlinger i en enkelt kjoring - tre av dem
    rettinger av samme kommentar. Over ti paa en sak er en lokke, og det er
    den sperren som faktisk fanger den. Det globale taket pa 60 gjor det
    ikke: der ville lokken fatt lov til a spise atte sakers budsjett forst."""
    X.set_autonomy("full", "test")
    X._mark_case_read(48423)
    for _ in range(X.MAX_ACTIONS_PER_CASE):
        assert X._krev_nivaa("add_case_comment", "kommenter", 48423) is None
        X._tell_handling(48423)
    svar = json.loads(X._krev_nivaa("add_case_comment", "kommenter", 48423))
    assert svar["arsak"] == "handlingstak_per_sak"
    assert svar["handlinger_paa_saken"] == X.MAX_ACTIONS_PER_CASE


def test_taket_per_sak_rammer_ikke_naboen():
    """Sperren skal stoppe lokken pa EN sak, ikke stanse hele helgevakten."""
    X.set_autonomy("full", "test")
    X._mark_case_read(48423)
    X._mark_case_read(48556)
    for _ in range(X.MAX_ACTIONS_PER_CASE):
        X._tell_handling(48423)
    assert json.loads(
        X._krev_nivaa("add_case_comment", "kommenter", 48423)
    )["arsak"] == "handlingstak_per_sak"
    assert X._krev_nivaa("add_case_comment", "kommenter", 48556) is None


def test_tell_handling_oker_begge_tellerne():
    """Kallstedene kaller _tell_handling(), ikke to linjer hver. En regel som
    ma gjentas pa hvert kallsted blir brutt pa det femte - slik fire verktoy
    havnet under mcp.run() uten a bli servert."""
    X._tell_handling(48423)
    X._tell_handling(48423)
    X._tell_handling(48556)
    assert X._actions_done == 3
    assert X._actions_per_case[48423] == 2
    assert X._actions_per_case[48556] == 1


def test_tell_handling_takler_sak_uten_nummer():
    X._tell_handling(None)
    assert X._actions_done == 1
    assert X._actions_per_case == {}


def test_det_globale_taket_romme_en_helgevakt():
    """Malt: en reell sak kostet 7 skrivehandlinger. Et tak pa 20 ga ~2-3
    saker per serverprosess, og telleren nullstilles ikke av en ny samtale.
    Taket skal stoppe en lopsk lokke, ikke en normal helg."""
    assert X.MAX_AUTONOMOUS_ACTIONS >= 7 * 8
    assert X.MAX_ACTIONS_PER_CASE < X.MAX_AUTONOMOUS_ACTIONS


def test_get_autonomy_viser_begge_takene():
    """Ser man bare det globale tallet, ser en sak som er i ferd med a bli
    lopsk identisk ut med en normal dag."""
    X._tell_handling(48423)
    r = json.loads(X.get_autonomy())
    assert r["tak_per_kjoring"] == X.MAX_AUTONOMOUS_ACTIONS
    assert r["tak_per_sak"] == X.MAX_ACTIONS_PER_CASE
    assert r["handlinger_per_sak"] == {"48423": 1}


def test_ukjent_nivaa_avvises():
    svar = json.loads(X.set_autonomy("halvveis"))
    assert svar["endret"] is False
    assert X.autonomy() == "les"


def test_miljovariabel_setter_nivaa(monkeypatch):
    monkeypatch.setattr(X, "_autonomy", None)
    monkeypatch.setenv("XSALE_AUTONOMY", "svar")
    assert X.autonomy() == "svar"


def test_soppel_i_miljovariabel_faller_til_les(monkeypatch):
    monkeypatch.setattr(X, "_autonomy", None)
    monkeypatch.setenv("XSALE_AUTONOMY", "ja takk")
    assert X.autonomy() == "les"


def test_avvisning_loggfores():
    """En helgekjoring skal kunne gjore rede for det den IKKE gjorde."""
    X._krev_nivaa("close_case", "full", 48423)
    rapport = json.loads(X.autonomy_report())
    assert rapport["avvist"] >= 1


def test_mark_case_read_takler_soppel():
    X._mark_case_read(None)
    X._mark_case_read("abc")
    assert X._cases_read == set()


def test_mark_case_read_normaliserer_streng():
    X._mark_case_read("48423")
    assert 48423 in X._cases_read


# --- Kundematching -------------------------------------------------------
#
# Bakgrunnen: XSALE ignorerer alle tekstfiltre stille. Sokene gikk derfor mot
# et lokalt register, og matchingen ma tale at navneformene varierer.

KUNDER = [
    {"id": 1, "navn": "TEKNISK VACUUM AS", "orgnr": "912345678"},
    {"id": 2, "navn": "Teknisk Vakuum Service", "orgnr": ""},
    {"id": 3, "navn": "LILLE LOV AS", "orgnr": "998877665"},
    {"id": 4, "navn": "Ming Restaurant AS", "orgnr": ""},
]


def test_eksakt_navn_forst():
    treff = X._match_kunder("TEKNISK VACUUM AS", KUNDER)
    assert treff[0]["id"] == 1


def test_delstreng_treffer():
    ider = [c["id"] for c in X._match_kunder("vacuum", KUNDER)]
    assert 1 in ider


def test_ordmengde_takler_ulik_rekkefolge():
    ider = [c["id"] for c in X._match_kunder("restaurant ming", KUNDER)]
    assert 4 in ider


def test_tom_soketekst_gir_ingenting():
    assert X._match_kunder("", KUNDER) == []
    assert X._match_kunder(None, KUNDER) == []


def test_maks_null_gir_ikke_tom_liste():
    """maks=0 ga tidligere null treff i stedet for standardgrensen."""
    assert len(X._match_kunder("teknisk", KUNDER, maks=0)) >= 1


# --- Mottakersperren -----------------------------------------------------
#
# Malt 21.09.2026: inboundEmail er en rå headerblokk, og regexen plukket
# Message-ID-er som gyldige adresser. En sperre som godtar søppel er verre
# enn ingen sperre, for den ser ut som den virker.

@pytest.mark.parametrize("adresse", [
    "as8pr09mb469361e116d4b544be01ce21a7bb2@as8pr09mb4693.eurprd09.prod.outlook.com",
    "dbapr01mb67601de48022332a69205ebfefb72@dbapr01mb6760.eurprd01.prod.exchangelabs.com",
    "",
    "ikke-en-adresse",
])
def test_messageid_avvises(adresse):
    assert X._ser_ut_som_messageid(adresse) is True


@pytest.mark.parametrize("adresse", [
    "karla_as1@hotmail.com",
    "may@maliprofil.no",
    "louise.lagergren@dnt.no",
    "support@plorea.com",
    "post@maliprofil.no",
])
def test_ekte_adresser_slipper_gjennom(adresse):
    assert X._ser_ut_som_messageid(adresse) is False


def test_statusverdiene_er_de_malte():
    """Malt pa 2000 levende saker. COMPLETED er lukket."""
    assert X.CASE_STATUSES == ("NEW", "ASSIGNED", "FEEDBACK", "ON_HOLD",
                               "COMPLETED")
    assert X.CLOSED_STATUS == "COMPLETED"


# --- Payload-formene, dyrt kjøpt ------------------------------------------
#
# Formene under ble funnet ved å opprette fire saker på TESTKUNDE
# 21.09.2026. Tre av dem ble opprettet ved et uhell, fordi
# POST /customercase/<id> ignorerer id-en i stien og oppretter en ny sak —
# med success:true og meldingen «Sak opprettet». Testene her finnes for at
# en senere endring ikke skal koste det samme igjen.

def test_put_finnes_og_brukes():
    """POST oppretter saker. Oppdatering MÅ gå via PUT."""
    assert hasattr(X, "_api_put")


def test_statuspayload_har_feltene_som_ellers_blankes():
    raa = {"id": 1, "customerId": 2, "subject": "s", "typeKey": "KEY_2",
           "priority": "LOW", "userId": 7687, "origin": "PHONE",
           "contactId": None, "notes": "", "requestedById": 7687, "type": "",
           "description": "<b>HTML som ikke skal ekkoes</b>",
           "tagId": [9999]}
    p = X._bygg_status_payload(raa, "COMPLETED")
    # Uten priority blankes den; uten customerId: "Kunne ikke finne kunde".
    assert p["priority"] == "LOW"
    assert p["customerId"] == 2
    assert p["status"] == "COMPLETED"
    # description skal IKKE med - å ekko den tilbake kan overskrive HTML-en.
    assert "description" not in p
    # tagId trengs ikke; den overlever uten å sendes (målt på sak 48641).
    assert "tagId" not in p


def test_statuspayload_pakker_ut_nostede_id():
    p = X._bygg_status_payload({"userId": {"id": 7687, "name": "Jalal"},
                                "customerId": 2}, "NEW")
    assert p["userId"] == 7687


# --- Ingen PUT naar statusen allerede stemmer -----------------------------
#
# close_case pa sak 48638, som alt var COMPLETED, ga en PUT som ikke endret
# noe og et svar som sa ut som en vellykket lukking - samme feilform som
# «success: true» pa noe helt annet enn det man ba om.
#
# Testene stubber saksoppslaget i stedet for a peke pa 48638. Den saken er en
# kastesak som skal slettes, og et bevis som forsvinner med vilje er ikke et
# bevis.

@pytest.fixture
def sak_i_status(monkeypatch):
    """Lar en test si hvilken status saken star i, uten a roere XSALE."""
    def lag(status):
        raa = {"id": 2994021, "customerId": 3192712, "subject": "Kastesak",
               "typeKey": "KEY_2", "priority": "LOW", "userId": 7687,
               "origin": "PHONE", "contactId": None, "notes": "",
               "requestedById": 7687, "type": "", "status": status}
        monkeypatch.setattr(X, "get_case_by_serial",
                            lambda serial_number: json.dumps({"id": 2994021}))
        monkeypatch.setattr(X, "_raa_sak", lambda case_id: dict(raa))
        return raa
    return lag


def test_close_case_melder_at_saken_alt_er_lukket(sak_i_status):
    sak_i_status("COMPLETED")
    svar = json.loads(X.close_case(48638, comment="Løst ved bytte av terminal.",
                                   dry_run=True))
    assert svar["changed"] is False
    assert svar["allerede_i_status"] is True
    assert svar["allerede_lukket"] is True
    assert "lukket" in svar["merknad"]
    # Ingen PUT er engang forberedt.
    assert "payload" not in svar


def test_ingenting_skrives_naar_statusen_alt_stemmer(sak_i_status, monkeypatch):
    """Heller ikke med dry_run=False - og kommentaren skal ikke gaa stille tapt.

    Vakten ligger foran bade dry_run og autonomikontrollen, sa dette kallet
    skal returnere uten a skrive noe som helst.
    """
    sak_i_status("COMPLETED")
    kalt = []
    monkeypatch.setattr(X, "add_case_comment",
                        lambda *a, **k: kalt.append("kommentar"))
    monkeypatch.setattr(X, "_api_put", lambda *a, **k: kalt.append("put"))

    svar = json.loads(X.close_case(48638, comment="Skal ikke forsvinne.",
                                   dry_run=False))
    assert kalt == [], kalt
    assert svar["kommentar_skrevet"] is False
    # Svaret ma si hva som skjedde med kommentaren, ikke bare utelate den.
    assert "add_case_comment" in svar["merknad"]


def test_vakten_gjelder_alle_statuser_ikke_bare_lukking(sak_i_status):
    """En stille no-op er like uheldig for ON_HOLD som for COMPLETED.

    «Statusen var allerede riktig» er dessuten nyttig signal i en autonom
    kjoering, ikke bare ved lukking.
    """
    sak_i_status("ON_HOLD")
    svar = json.loads(X.set_case_status(48638, "ON_HOLD", dry_run=True))
    assert svar["allerede_i_status"] is True
    # «Lukket» er close_case sitt ord, ikke set_case_status sitt.
    assert "allerede_lukket" not in svar


def test_ekte_statusendring_gaar_som_for(sak_i_status):
    """Vakten skal vaere smal: en faktisk endring bygger payload som for."""
    sak_i_status("COMPLETED")
    svar = json.loads(X.set_case_status(48638, "FEEDBACK", dry_run=True))
    assert "allerede_i_status" not in svar
    assert svar["fra_status"] == "COMPLETED"
    assert svar["payload"]["status"] == "FEEDBACK"


def test_epostpayload_bruker_content_og_to_som_liste():
    """Feltnavnene er content og to, ikke body og receiver."""
    p = X._bygg_epost_payload(2994021, "Emne", "<b>Hei</b>", "kunde@eksempel.no")
    assert p["content"] == "<b>Hei</b>"
    assert p["to"] == ["kunde@eksempel.no"]   # streng gir "to should not be blank"
    assert isinstance(p["to"], list)
    assert "body" not in p and "receiver" not in p
    # Avsender settes serverside.
    assert "sender" not in p and "from" not in p
    assert p["model"] == "Customercase"
    assert p["action"] == "email/send"
    assert p["fk"] == 2994021


def test_epostpayload_deler_cc_paa_komma_og_semikolon():
    p = X._bygg_epost_payload(1, "E", "<p>x</p>", "a@b.no", cc="c@d.no; e@f.no")
    assert p["cc"] == ["c@d.no", "e@f.no"]


def test_epostpayload_utelater_tom_cc():
    p = X._bygg_epost_payload(1, "E", "<p>x</p>", "a@b.no", cc="")
    assert "cc" not in p


# --- Transliterert norsk --------------------------------------------------
#
# 21.09.2026 skrev jeg fem kommentarer og to e-poster til XSALE der all norsk
# tekst var ASCII-transliterert — «Formalet er a bekrefte», «Kontroller
# utfort», og «skal sta uroert», som ikke er et ord i noen rettskrivning.
# Verktøyet var aldri i veien: æøå går byte-identisk gjennom både
# add_case_comment (558 tegn) og reply_to_customer (457 tegn). Vanen var min.

def test_fanger_min_egen_transliterering():
    funn, uten = X._finn_transliterert_norsk(
        "Formalet er a bekrefte at kontrollen er utfort og at feltet "
        "skal sta uroert. Det er ogsa arsaken til at saken maa apnes "
        "paa nytt, og vi gjor det forst i morgen som avtalt med kunden.")
    feil = [a for a, _ in funn]
    for ord_ in ("formalet", "utfort", "uroert", "ogsa", "arsaken", "forst"):
        assert ord_ in feil, ord_
    assert uten is True


def test_riktig_norsk_gir_ingen_advarsel():
    assert X._norskvarsel(
        "Formålet er å bekrefte at overføringen av dagsoppgjøret virker. "
        "Kontrollen er utført, og årsaken til avviket er funnet. Feltet "
        "står urørt, og vi tar kontakt med kunden i morgen.") is None


def test_engelsk_tekst_slipper_gjennom():
    """JIRA skrives på engelsk — den må ikke fanges."""
    assert X._norskvarsel(
        "The settlement export fails because the voucher lines do not sum "
        "to zero. This affects 41 customers and 228 settlements. The root "
        "cause is that invoiced orders are excluded from the payload but "
        "are still counted in the total, so the voucher never balances.") is None


def test_kort_ascii_notat_slipper_gjennom():
    assert X._norskvarsel("Ringte kunden, ingen svar.") is None


def test_lost_og_mate_gir_ikke_falske_treff():
    """Vanlige engelske ord skal ikke stå i lista."""
    assert "lost" not in X.TRANSLITTERERT_NORSK
    assert "mate" not in X.TRANSLITTERERT_NORSK


def test_aeoeaa_overlever_konverteringen():
    """Målt byte-identisk mot XSALE; her holdes konverteringen ærlig."""
    inn = ("**ÆØÅ** og æøå: blåbærsyltetøy, dagsoppgjør, «anførselstegn», "
           "– tankestrek, entrée, müsli")
    ut = X._markdown_to_xsale_html(inn)
    for tegn in "ÆØÅæøå«»–éü":
        assert tegn in ut, tegn


def test_aeoeaa_i_tabell_og_liste():
    ut = X._markdown_to_xsale_html(
        "| Ord | Hvorfor |\n|---|---|\n| dagsoppgjør | ø |\n\n- påløpte renter")
    assert "dagsoppgjør" in ut
    assert "påløpte" in ut


def test_signatur_beholder_norske_tegn():
    """Signaturen brukes til å verifisere skriv — den må ikke miste tegn."""
    sign = X._text_signature("<b>Blåbærsyltetøy</b> på Håkons kjøkken")
    assert "blåbærsyltetøy" in sign
    assert "håkons" in sign


def test_suffiks_fanger_sammensetninger():
    """«skriveverktoy» slapp gjennom en hele-ord-liste. Sammensetning er
    normen i norsk fagsjargong, så suffiksene må med.

    Forledd («arsberetning») har ingen egen regel — «ars-» som prefiks er
    for lett å treffe feil med. De ordene står eksplisitt i hovedlisten.
    """
    for tekst, ventet in (
            ("TEST - verifisering av skriveverktoy", "skriveverktøy"),
            ("Overforing av dagsoppgjor feiler", "dagsoppgjør"),
            ("Kontroller arsberetningen", "årsberetningen"),  # helt ord
            ("Se palopte renter", "påløpte"),                  # helt ord
    ):
        funn, _ = X._finn_transliterert_norsk(tekst)
        rettet = [b for _, b in funn]
        assert any(ventet in r for r in rettet), (tekst, rettet)


@pytest.mark.parametrize("tekst", [
    "The tool fails to deploy the employed worker",
    "Vi har verktøy for dette",
    "Overføring av dagsoppgjøret feiler",
    "Check the gebyr settings",
])
def test_suffiks_gir_ikke_falske_treff(tekst):
    funn, _ = X._finn_transliterert_norsk(tekst)
    assert funn == [], (tekst, funn)


def test_suffiks_krever_sammensetning():
    """Selve ordet står i hovedlisten; suffiksregelen skal ikke dublere."""
    funn, _ = X._finn_transliterert_norsk("arsak")
    assert [a for a, _ in funn] == ["arsak"]


def test_verktoybeskrivelsene_er_pa_ordentlig_norsk():
    """Docstringene er verktøybeskrivelsene Jalal ser i verktøylista.

    De sto i ASCII-norsk — «Viser gjeldende autonominivaa», «Finner en kunde
    paa navn» — helt til han påpekte det 21.09.2026. Denne testen holder dem
    der.
    """
    import asyncio
    verktoy = asyncio.run(X.mcp.list_tools())
    syndere = {}
    for t in verktoy:
        v = X._norskvarsel(t.description or "")
        if v and v.get("feilstavede_ord"):
            syndere[t.name] = v["feilstavede_ord"]
    assert not syndere, syndere


def test_verktoydekoratorene_kjorer_ved_import():
    """27 funksjoner er dekorert med @mcp.tool(), og dekoratorene kjører.

    Dette er importbildet, og det er alt testen kan vite. Den gjør `import
    mcp_server`, og da er __name__ ikke "__main__", så mcp.run() hoppes over og
    hele fila kjøres. Testen ser derfor alle dekoratorene uansett hvor i fila de
    står — også dem serveren aldri rekker å registrere.

    Den het «test_alle_verktoy_er_registrert» fram til 21.09.2026, og passerte
    med 27 mens katalogen serverte 23. Navnet lovet noe den ikke kunne se.

    Påstanden om registrering eies nå av to andre:
    test_ingen_verktoy_defineres_etter_serverstarten leser kildeteksten, og
    sjekk_servert_katalog.py spør en ekte serverprosess.

    Det denne fanger, er at en dekorator feiler, eller at et verktøy faller helt
    ut av fila.
    """
    import asyncio
    navn = {t.name for t in asyncio.run(X.mcp.list_tools())}
    for paakrevd in ("reply_to_customer", "set_case_status", "close_case",
                     "edit_case_comment", "add_case_comment", "search_cases",
                     "find_customer", "get_autonomy", "set_autonomy"):
        assert paakrevd in navn, paakrevd
    assert len(navn) == 27, sorted(navn)


def test_ingen_verktoy_defineres_etter_serverstarten():
    """Et @mcp.tool() under `if __name__ == "__main__"` blir aldri registrert.

    21.09.2026: fire skriveverktøy manglet i katalogen. De sto i fila, hadde
    grønne tester og var kjørt live. Årsaken var plassering — commit 44e7e4c
    la seksjonen til under `mcp.run()` på linje 2683, og Python kjører ovenfra
    og ned. Serveren startet og blokkerte før dekoratorene under kjørte.
    Katalogen serverte 23 av 27.

    test_verktoydekoratorene_kjorer_ved_import kunne ikke fange det. Den gjør
    `import mcp_server`, og ved import er __name__ ikke "__main__", så mcp.run()
    hoppes over og hele fila kjøres. Alle 27 registreres, og testen blir grønn
    mens serveren serverer 23.

    Derfor leser denne testen KILDETEKSTEN. Den importerte modulen kan ikke
    vise forskjellen, for forskjellen er nettopp at importen oppfører seg
    annerledes enn `python mcp_server.py`.
    """
    kilde = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "mcp_server.py")
    with io.open(kilde, encoding="utf-8") as f:
        tre = ast.parse(f.read())

    startlinje = None
    for node in tre.body:
        if isinstance(node, ast.If) and "__main__" in ast.dump(node.test):
            startlinje = node.lineno
    assert startlinje is not None, (
        "Fant ingen `if __name__ == \"__main__\"`-blokk. Er den fjernet, "
        "måler ikke denne testen noe.")

    etter = []
    for node in tre.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            mål = d.func if isinstance(d, ast.Call) else d
            if getattr(mål, "attr", None) == "tool" and node.lineno > startlinje:
                etter.append((node.lineno, node.name))

    assert not etter, (
        "Disse verktøyene er definert etter serverstarten på linje %d og blir "
        "aldri registrert: %s. Flytt dem over startblokken."
        % (startlinje, ", ".join("%s (linje %d)" % (n, l) for l, n in etter)))


def test_svarnokler_er_ascii():
    """Nøklene er grensesnittet. De skal ikke få diakritiske tegn.

    Da jeg rettet norsk i kilden, omdøpte et for grovt søk nøkkelen «arsak»
    til «årsak» og brøt både tester og kallere. Testen sjekker atferden, ikke
    kildeteksten — «årsak» finnes helt riktig som *verdi* i ordlisten.
    """
    X.set_autonomy("les", "test")
    X._mark_case_read(48423)
    svar = json.loads(X._krev_nivaa("close_case", "full", 48423))
    assert "arsak" in svar, sorted(svar)
    assert "årsak" not in svar

    X.set_autonomy("full", "test")
    X._actions_done = X.MAX_AUTONOMOUS_ACTIONS
    tak = json.loads(X._krev_nivaa("add_case_comment", "kommenter", 48423))
    assert tak["arsak"] == "handlingstak"

    rapport = json.loads(X.autonomy_report())
    assert "totalt_loggfort" in rapport


def test_meldingstekstene_er_pa_ordentlig_norsk():
    """Prosaen i svarene, til forskjell fra nøklene."""
    X.set_autonomy("les", "test")
    X._mark_case_read(48423)
    svar = json.loads(X._krev_nivaa("close_case", "full", 48423))
    forklaring = svar.get("forklaring", "")
    assert "nivå" in forklaring, forklaring
    assert "nivaa" not in forklaring

    X.set_autonomy("full", "test")
    ulest = json.loads(X._krev_nivaa("close_case", "full", 99999))
    assert X._norskvarsel(ulest["forklaring"]) is None, ulest["forklaring"]


# --- Luft etter blokkelementer --------------------------------------------
#
# Funnet 21.09.2026 ved å se på e-posten slik Outlook viser den, ikke på
# HTML-en. «Hva som gjenstår etter dette» klistret seg til tabellen over.
# Verre enn kosmetikk: XSALE stripper taggene i tidslinjevisningen, og da
# smeltet ordene sammen — kommentaren på sak 48638 leses som «kr 1 234,56
# med hardt mellomromFeltet orgno er urørt».

@pytest.mark.parametrize("markdown,blokk", [
    ("| A | B |\n|---|---|\n| 1 | 2 |\n\nAvsnitt etter.", "</table>"),
    ("- ett\n- to\n\nAvsnitt etter.", "</ul>"),
    ("1. ett\n2. to\n\nAvsnitt etter.", "</ol>"),
])
def test_luft_etter_blokkelement(markdown, blokk):
    ut = X._markdown_to_xsale_html(markdown)
    i = ut.find(blokk)
    assert i != -1, (blokk, ut)
    assert ut[i + len(blokk):].startswith("<br"), ut


def test_ordene_smelter_ikke_sammen_naar_taggene_strippes():
    """Tidslinjevisningen i XSALE stripper taggene. Da må ordene skilles."""
    ut = X._markdown_to_xsale_html(
        "- kr 1 234,56 med hardt mellomrom\n\nFeltet orgno er urørt.")
    vasket = re.sub(r"<[^>]+>", " ", ut)
    assert "mellomromFeltet" not in vasket
    assert "mellomrom" in vasket and "Feltet" in vasket


def test_blokkluft_gir_ikke_trippel_br():
    """Fiksen skal ikke bytte for lite luft med for mye."""
    ut = X._markdown_to_xsale_html("- ett\n\nTekst.\n\n- to")
    assert "<br><br><br>" not in ut


# --- Mottakerregelen ------------------------------------------------------
#
# Jalals regel 22.09.2026: kontaktpersonens e-post er den autoritative
# mottakeren; kundekortet er reserven når kontakten mangler e-post.
#
# Bekreftet empirisk på sak 48661, der de to har ULIKE domener
# (albatrossfitness.no mot albatrossenter.no) og kollegaen sendte til
# kontaktpersonen.
#
# Regelen så riktig ut på 48661 og var brukket på tre av fem reelle saker:
# «siste innkommende» ble support@plorea.com, altså oss selv, fordi interne
# varselkopier av vår egen utgående post klassifiseres som innkommende.

def _stub_sak(monkeypatch, kontakt_epost=None, kundekort=None,
              innkommende=None, contact_id=7):
    """Stubber de to oppslagene _case_epostadresser gjør."""
    kontakter = []
    if contact_id:
        kontakter.append({"id": contact_id, "firstname": "Kari",
                          "lastname": "Kunde", "email": kontakt_epost or ""})
    detalj = {
        "contactId": contact_id,
        "customer": {"email": kundekort or "", "contacts": kontakter},
        "replyTo": {"email": "support+1@plorea.inbound.xsale.no"},
        "inboundEmail": [],
    }
    poster = [{"id": 1, "direction": "inbound_or_notice", "sender": s,
               "receiver": "support@plorea.com", "subject": "x"}
              for s in (innkommende or [])]
    monkeypatch.setattr(X, "get_case_details",
                        lambda cid: json.dumps(detalj))
    monkeypatch.setattr(X, "get_case_emails",
                        lambda sn, include_bodies=True: json.dumps(
                            {"emails": poster}))
    monkeypatch.setattr(X, "_egne_domener_cache", {"plorea.com", "amendo.no"})


def test_kontaktperson_slaar_kundekortet(monkeypatch):
    _stub_sak(monkeypatch, kontakt_epost="kari@kunde.no",
              kundekort="gammel@annetdomene.no")
    adr, kilde, konflikt = X._anbefalt_mottaker(1, 1)
    assert adr == "kari@kunde.no"
    assert kilde == "kontaktperson"
    assert konflikt is None


def test_kundekortet_brukes_naar_kontakten_mangler_epost(monkeypatch):
    """Jalals regel: mangler kontakten e-post, kan kundekortet benyttes."""
    _stub_sak(monkeypatch, kontakt_epost="", kundekort="post@kunde.no")
    adr, kilde, _ = X._anbefalt_mottaker(1, 1)
    assert adr == "post@kunde.no"
    assert kilde == "kundekortet"


def test_kundekortet_brukes_naar_ingen_kontakt_er_satt(monkeypatch):
    _stub_sak(monkeypatch, kundekort="post@kunde.no", contact_id=None)
    adr, kilde, _ = X._anbefalt_mottaker(1, 1)
    assert adr == "post@kunde.no"
    assert kilde == "kundekortet"


def test_egen_adresse_blir_aldri_mottaker(monkeypatch):
    """Uten dette ble support@plorea.com valgt som mottaker på sak 48638."""
    _stub_sak(monkeypatch, kontakt_epost="", kundekort="",
              innkommende=["support@plorea.com", "jalal@plorea.com"],
              contact_id=None)
    adr, kilde, konflikt = X._anbefalt_mottaker(1, 1)
    assert adr is None, (adr, kilde)
    assert konflikt


def test_egen_utgaaende_kopi_gir_ikke_falsk_konflikt(monkeypatch):
    """Interne varselkopier kom tilbake som «innkommende» og utløste konflikt
    på tre av fem reelle saker."""
    _stub_sak(monkeypatch, kontakt_epost="kari@kunde.no",
              kundekort="kari@kunde.no",
              innkommende=["support@plorea.com"])
    adr, kilde, konflikt = X._anbefalt_mottaker(1, 1)
    assert adr == "kari@kunde.no"
    assert konflikt is None, konflikt


def test_ekte_ekstern_avsender_gir_konflikt(monkeypatch):
    """Skrev en ANNEN enn kontaktpersonen inn sist, skal koden si fra."""
    _stub_sak(monkeypatch, kontakt_epost="kari@kunde.no",
              kundekort="kari@kunde.no",
              innkommende=["kollega@kunde.no"])
    adr, kilde, konflikt = X._anbefalt_mottaker(1, 1)
    assert kilde == "kontaktperson"
    assert konflikt and "kollega@kunde.no" in konflikt


@pytest.mark.parametrize("adresse,egen", [
    ("support@plorea.com", True),
    ("jalal@plorea.com", True),
    ("louise.lagergren@amendo.no", True),
    ("noreply@kunde.no", True),
    ("kari@kunde.no", False),
    ("ingunn@albatrossfitness.no", False),
])
def test_gjenkjenner_egne_adresser(monkeypatch, adresse, egen):
    monkeypatch.setattr(X, "_egne_domener_cache",
                        {"plorea.com", "amendo.no", "done.ai"})
    assert X._er_egen_adresse(adresse) is egen


def test_prioriteten_er_uttalt():
    """Rekkefølgen lå tidligere implisitt i hvilken kilde som ble lest først."""
    assert X.MOTTAKER_PRIORITET[0] == "kontaktperson"
    assert "kundekortet" in X.MOTTAKER_PRIORITET
    assert X.MOTTAKER_PRIORITET.index("kontaktperson") < \
        X.MOTTAKER_PRIORITET.index("kundekortet")
    assert "oss" not in X.MOTTAKER_PRIORITET


def test_epostpayload_setter_replyto_naar_den_er_oppgitt():
    """Uten replyTo satte XSALE Reply-To til support@plorea.com, og kundens
    svar ville landet i den generelle innboksen uten kobling til saken.
    Målt 22.09.2026, og verifisert ved å sende feltet."""
    p = X._bygg_epost_payload(
        2994021, "Emne", "<p>Hei</p>", "kunde@eksempel.no",
        reply_to="support+48638@plorea.inbound.xsale.no")
    assert p["replyTo"] == "support+48638@plorea.inbound.xsale.no"


def test_epostpayload_utelater_tom_replyto():
    p = X._bygg_epost_payload(1, "E", "<p>x</p>", "a@b.no", reply_to="")
    assert "replyTo" not in p
    p2 = X._bygg_epost_payload(1, "E", "<p>x</p>", "a@b.no")
    assert "replyTo" not in p2
