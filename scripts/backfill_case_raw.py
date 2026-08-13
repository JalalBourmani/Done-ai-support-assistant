# -*- coding: utf-8 -*-
"""
Engangsskript: lager case_raw.json i eksisterende Auto-XSALE-saksmapper.

Frontenden (auto_axale_app) leser case_raw.json for a vise kunde, emne, status,
prioritet og datoer i sakslistene. Mapper laget for prompten fikk dette steget
mangler fila, og viser derfor bare streker.

Skriver KUN de sju feltene frontenden faktisk leser. Kundenotatet i XSALE
inneholder ofte passord, PIN-koder og API-nokler, og skal ikke til disk.

Idempotent: hopper over mapper som allerede har fila, sa skriptet kan kjores
pa nytt etter avbrudd. Bruk --force for a skrive om alle.

Saksmappen finnes i denne rekkefolgen: --root, sa AUTO_XSALE_DIR, sa
%USERPROFILE%\\Documents\\Auto-XSALE.

Kjores med legitimasjon lastet, f.eks.:

    . .\\scripts\\common.ps1
    Import-ConfigEnv
    Import-EncryptedCredential -Path .\\secrets\\xsale.xml `
        -UsernameVariable XSALE_EMAIL -PasswordVariable XSALE_PASSWORD
    & .\\.venv\\Scripts\\python.exe .\\scripts\\backfill_case_raw.py --dry-run

Kjor alltid --dry-run forst. Skriptet skriver filer.
"""
import json
import os
import sys
import time

# Stier utledes fra hvor dette skriptet ligger, aldri hardkodet. Den gamle
# versjonen pekte pa en bestemt brukers hjemmemappe og feilet med ImportError for
# alle andre. Og fordi skriptet SKRIVER filer, er en feil rot verre enn en
# feilmelding: da havner case_raw.json i noen andres mapper, eller ingen steder.
_HER = os.path.dirname(os.path.abspath(__file__))
_KIT = os.path.dirname(_HER)
sys.path.insert(0, os.path.join(_KIT, "servers", "xsale"))
import mcp_server


def _finn_rot():
    """Saksmappen. --root vinner, sa AUTO_XSALE_DIR, sa standardplasseringen."""
    if "--root" in sys.argv:
        return sys.argv[sys.argv.index("--root") + 1]
    fra_miljo = os.environ.get("AUTO_XSALE_DIR")
    if fra_miljo:
        return fra_miljo
    return os.path.join(os.path.expanduser("~"), "Documents", "Auto-XSALE")


ROT = _finn_rot()
FORCE = "--force" in sys.argv
DRY = "--dry-run" in sys.argv

if not os.path.isdir(ROT):
    sys.exit("Fant ikke saksmappen: %s\n"
             "Sett AUTO_XSALE_DIR i config.env, eller bruk --root <sti>." % ROT)

# Nyaktig de feltene lib/cases.ts -> readCaseMeta() leser.
FELT = ("serialNumber", "subject", "status", "priority", "origin", "created", "updated")


def trimmet(sak):
    """Plukk ut kun det frontenden trenger. Ukjent felt blir null, ikke gjetning."""
    ut = {f: sak.get(f) for f in FELT}
    kunde = sak.get("customer") or {}
    ut["customer"] = {
        "name": kunde.get("name"),
        "serialNumber": kunde.get("serialNumber"),
    }
    return ut


def main():
    mapper = sorted(
        (d for d in os.listdir(ROT)
         if d.isdigit() and os.path.isdir(os.path.join(ROT, d))),
        key=int,
    )
    print("Fant %d numeriske saksmapper i %s" % (len(mapper), ROT))
    if DRY:
        print("DRY-RUN: ingenting skrives.\n")
    if FORCE:
        print("FORCE: skriver om ogsa mapper som allerede har fila.\n")

    mcp_server._get_session()
    print("Innlogget som bruker-ID %s\n" % mcp_server._user_id)

    skrevet = hoppet = feilet = 0
    problemer = []
    t0 = time.time()

    for i, nr in enumerate(mapper, 1):
        mal = os.path.join(ROT, nr, "case_raw.json")
        if os.path.exists(mal) and not FORCE:
            hoppet += 1
            continue

        try:
            sak = json.loads(mcp_server.get_case_by_serial(int(nr)))
        except Exception as exc:
            feilet += 1
            problemer.append((nr, "oppslag feilet: %s" % exc))
            print("[%3d/%d] %-7s FEIL   %s" % (i, len(mapper), nr, exc))
            continue

        if "error" in sak:
            feilet += 1
            problemer.append((nr, sak["error"]))
            print("[%3d/%d] %-7s IKKE FUNNET" % (i, len(mapper), nr))
            continue

        data = trimmet(sak)
        kunde = (data.get("customer") or {}).get("name") or "(ukjent kunde)"

        if not DRY:
            # utf-8 uten BOM - appen tolererer BOM na, men vi lager den ikke.
            with open(mal, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")

        skrevet += 1
        print("[%3d/%d] %-7s OK     %-34s %s" % (
            i, len(mapper), nr, kunde[:34], (data.get("subject") or "")[:40]))

    print("\n" + "=" * 66)
    print("Skrevet: %d   Hoppet over (fila fantes): %d   Feilet: %d" % (
        skrevet, hoppet, feilet))
    print("Tid: %.1f min" % ((time.time() - t0) / 60))
    if problemer:
        print("\nSaker som ikke kunne hentes:")
        for nr, hvorfor in problemer:
            print("  %-7s %s" % (nr, str(hvorfor)[:90]))


if __name__ == "__main__":
    main()
