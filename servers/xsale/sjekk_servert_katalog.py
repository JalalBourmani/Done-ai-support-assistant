# -*- coding: utf-8 -*-
"""Sjekker hva serveren FAKTISK serverer over MCP.

Kjøres for hånd, ikke i den raske suiten:

    python sjekk_servert_katalog.py

Dette er den sanne verifiseringen, og den eneste som kan se forskjell på «koden
finnes» og «verktøyet er tilgjengelig». Den starter en ekte serverprosess og
spør den over stdio, slik en klient gjør.

Bakgrunnen er 21.09.2026. Fire skriveverktøy lå under `if __name__ ==
"__main__": mcp.run()`, så dekoratorene kjørte aldri og katalogen serverte 23
av 27. Testene var grønne hele veien, fordi de gjør `import mcp_server` — og
ved import er __name__ ikke "__main__", så hele fila kjøres og alt registreres.
Importen og serveren oppfører seg ulikt, og bare det å snakke med serveren
viser det.

test_regresjon.py har en billig AST-variant som fanger nettopp den feilen på
hver endring. Denne er tregere og mer skjør — den starter en prosess — men den
måler det som faktisk gjelder. Kjør den når verktøy legges til eller flyttes,
og før repoet leveres fra seg.

Trenger ingen legitimasjon: _get_env() kalles først fra _get_session(), som er
lat, så tools/list svarer uten at serveren har snakket med XSALE.

Den må derimot kjøre i SAMME Python-miljø som den ekte serveren, ellers måler
den en annen installasjon enn den som brukes. Første versjon av denne sjekken
brukte sys.executable og traff system-Python med mcp 1.26.0, mens launcheren
kjører venv-en med 1.29.0. Rekkefølgen under er derfor: --python, så
XSALE_MCP_PYTHON, så venv-en launcheren bruker, og til slutt sys.executable.
Tolken skrives alltid ut, så et feil miljø ikke kan gå stille igjennom.
"""

import ast
import io
import itertools
import json
import os
import subprocess
import sys
import threading

HER = os.path.dirname(os.path.abspath(__file__))
KILDE = os.path.join(HER, "mcp_server.py")

# Slik launcheren gjor det: Claude-Code-Auto-XSALE/.venv ved siden av repoet.
# Se Claude-Code-Auto-XSALE/scripts/common.ps1.
VENV = os.path.join(os.path.dirname(HER), "Claude-Code-Auto-XSALE", ".venv")


def finn_python():
    """Tolken serveren faktisk kjores med, og hvor valget kom fra."""
    for flagg, verdi in zip(sys.argv, sys.argv[1:]):
        if flagg == "--python":
            return verdi, "--python"
    fra_miljo = os.getenv("XSALE_MCP_PYTHON")
    if fra_miljo:
        return fra_miljo, "XSALE_MCP_PYTHON"
    for underkatalog in ("Scripts/python.exe", "bin/python"):
        kandidat = os.path.join(VENV, *underkatalog.split("/"))
        if os.path.exists(kandidat):
            return kandidat, "venv-en launcheren bruker"
    return sys.executable, "sys.executable - FANT IKKE VENV-EN"


def verktoy_i_kilden():
    """Navnene på @mcp.tool()-funksjonene slik de står i kildeteksten."""
    with io.open(KILDE, encoding="utf-8") as f:
        tre = ast.parse(f.read())
    navn = set()
    for node in tre.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            mål = d.func if isinstance(d, ast.Call) else d
            if getattr(mål, "attr", None) == "tool":
                navn.add(node.name)
    return navn


def verktoy_serveren_tilbyr(python):
    """Starter mcp_server.py som egen prosess og ber om tools/list."""
    p = subprocess.Popen([python, KILDE], cwd=HER,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", bufsize=1)
    feil = []
    threading.Thread(target=lambda: [feil.append(l) for l in p.stderr],
                     daemon=True).start()
    teller = itertools.count(1)

    def send(obj):
        p.stdin.write(json.dumps(obj) + "\n")
        p.stdin.flush()

    def kall(metode, params):
        i = next(teller)
        send({"jsonrpc": "2.0", "id": i, "method": metode, "params": params})
        while True:
            linje = p.stdout.readline()
            if not linje:
                raise RuntimeError("Serveren svarte ikke. stderr:\n"
                                   + "".join(feil[-30:]))
            linje = linje.strip()
            if linje.startswith("{"):
                svar = json.loads(linje)
                if svar.get("id") == i:
                    return svar

    try:
        init = kall("initialize",
                    {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "sjekk_servert_katalog",
                                    "version": "1"}})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        svar = kall("tools/list", {})
        info = init.get("result", {}).get("serverInfo", {})
        return {t["name"] for t in svar["result"]["tools"]}, info
    finally:
        p.terminate()


def main():
    python, kilde_til_valget = finn_python()
    i_kilden = verktoy_i_kilden()
    servert, info = verktoy_serveren_tilbyr(python)

    print("Tolk:   %s  (%s)" % (python, kilde_til_valget))
    print("Server: %s %s" % (info.get("name", "?"), info.get("version", "")))
    print("I kilden:  %d" % len(i_kilden))
    print("Servert:   %d" % len(servert))

    mangler = sorted(i_kilden - servert)
    ekstra = sorted(servert - i_kilden)

    if mangler:
        print("\nDefinert i kilden, men IKKE servert:")
        for n in mangler:
            print("  - %s" % n)
        print("\nVanligste årsak: verktøyet er definert etter "
              "`if __name__ == \"__main__\": mcp.run()`.")
    if ekstra:
        print("\nServert, men ikke funnet i kilden (registrert et annet sted?):")
        for n in ekstra:
            print("  + %s" % n)

    if mangler or ekstra:
        print("\nAVVIK. Katalogen er ikke det kilden sier.")
        return 1

    print("\nOK. Alle %d verktøyene i kilden blir servert." % len(i_kilden))
    return 0


if __name__ == "__main__":
    sys.exit(main())
