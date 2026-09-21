# -*- coding: utf-8 -*-
"""Starter en MCP-server slik Claude Code gjor det, og fullforer et handtrykk.

Test-Path forteller bare at en fil finnes. Dette forteller at serveren faktisk
starter, snakker protokoll og eksponerer verktoy - som er det brukeren trenger.

Bruk:  python mcp_smoketest.py <xsale|mysql|kunnskap> [--tool NAVN]
Skriver "OK <detaljer>" eller "FEIL: <arsak>" og setter exit-kode.
"""
import json
import os
import subprocess
import sys
import threading
import time

KIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMEOUT = int(os.environ.get("MCP_SMOKETEST_TIMEOUT", "180"))


def main():
    if len(sys.argv) < 2:
        print("FEIL: mangler servernavn")
        return 2
    server = sys.argv[1]
    krevd_verktoy = None
    if "--tool" in sys.argv:
        krevd_verktoy = sys.argv[sys.argv.index("--tool") + 1]

    cmd = [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        os.path.join(KIT_ROOT, "scripts", "run-mcp.ps1"), "-Server", server,
    ]

    # pydantic_settings gir en IncompleteFieldDefinitionWarning via mcp-pakken.
    # Den er harmlos, men fyller stderr og far en fungerende server til a se
    # odelagt ut i verify-utdataen.
    miljo = dict(os.environ)
    miljo.setdefault("PYTHONWARNINGS", "ignore")

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=miljo,
        )
    except Exception as e:
        print("FEIL: klarte ikke starte run-mcp.ps1: %s" % e)
        return 1

    stderr_buf = []
    threading.Thread(
        target=lambda: [stderr_buf.append(l.rstrip()) for l in proc.stderr],
        daemon=True,
    ).start()

    def send(method, params=None, msg_id=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if msg_id is not None:
            msg["id"] = msg_id
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def read(msg_id):
        frist = time.time() + TIMEOUT
        while time.time() < frist:
            if proc.poll() is not None:
                raise RuntimeError("serveren avsluttet (kode %s). stderr:\n%s"
                                   % (proc.returncode, "\n".join(stderr_buf[-8:])))
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("serveren lukket stdout. stderr:\n%s"
                                   % "\n".join(stderr_buf[-8:]))
            line = line.strip()
            if not line:
                continue
            try:
                svar = json.loads(line)
            except ValueError:
                continue
            if svar.get("id") == msg_id:
                return svar
        raise RuntimeError("tidsavbrudd etter %ds. stderr:\n%s"
                           % (TIMEOUT, "\n".join(stderr_buf[-8:])))

    try:
        send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "verify", "version": "1.0"},
        }, msg_id=1)
        svar = read(1)
        if "result" not in svar:
            print("FEIL: handtrykk avvist: %s" % json.dumps(svar)[:200])
            return 1
        navn = (svar["result"].get("serverInfo") or {}).get("name", server)

        send("notifications/initialized", {})
        send("tools/list", {}, msg_id=2)
        svar = read(2)
        verktoy = [t["name"] for t in (svar.get("result") or {}).get("tools", [])]
        if not verktoy:
            print("FEIL: serveren startet men eksponerer ingen verktoy")
            return 1
        if krevd_verktoy and krevd_verktoy not in verktoy:
            print("FEIL: mangler verktoyet '%s'. Fant: %s" % (krevd_verktoy, ", ".join(verktoy)))
            return 1

        print("OK %s - %d verktoy (%s)" % (navn, len(verktoy), ", ".join(verktoy[:4])))
        return 0
    except Exception as e:
        print("FEIL: %s" % str(e)[:600])
        return 1
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
