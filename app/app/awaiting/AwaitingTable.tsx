"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { CaseSummary } from "@/lib/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { StatusBadge } from "../components/Badge";
import { IconExternal } from "../components/Icons";

/** Days a case has been parked before it deserves a nudge. */
const NUDGE_AFTER_DAYS = 7;

function daysWaiting(since: string | null): number | null {
  if (!since) return null;
  const t = new Date(since).getTime();
  if (Number.isNaN(t)) return null;
  return Math.floor((Date.now() - t) / 86400000);
}

export default function AwaitingTable({ cases }: { cases: CaseSummary[] }) {
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return cases;
    return cases.filter(
      (c) =>
        c.caseNumber.includes(needle) ||
        (c.meta.customer || "").toLowerCase().includes(needle) ||
        (c.meta.subject || "").toLowerCase().includes(needle) ||
        (c.awaitingNote || "").toLowerCase().includes(needle),
    );
  }, [cases, q]);

  const stale = cases.filter((c) => (daysWaiting(c.awaitingSince) ?? 0) >= NUDGE_AFTER_DAYS);

  return (
    <div className="panel">
      <div className="panel-head" style={{ gap: 12, flexWrap: "wrap" }}>
        <h2>{cases.length} saker venter på svar</h2>
        {stale.length > 0 && (
          <span className="badge badge-amber" title={`Ventet i ${NUDGE_AFTER_DAYS} dager eller mer`}>
            {stale.length} trenger purring
          </span>
        )}
        <input
          className="btn btn-ghost"
          style={{ minWidth: 240, cursor: "text" }}
          placeholder="Søk saksnr, kunde, emne…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Sak</th>
              <th>Kunde / emne</th>
              <th>XSALE-status</th>
              <th>Venter siden</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="muted" style={{ textAlign: "center", padding: 30 }}>
                  Ingen saker {q ? "matcher søket" : "venter på svar"}.
                </td>
              </tr>
            )}
            {rows.map((c) => {
              const d = daysWaiting(c.awaitingSince);
              const isStale = (d ?? 0) >= NUDGE_AFTER_DAYS;
              return (
                <tr
                  key={c.caseNumber}
                  className="clickable"
                  onClick={() => (window.location.href = `/cases/${c.caseNumber}`)}
                >
                  <td>
                    <Link
                      href={`/cases/${c.caseNumber}`}
                      className="case-num"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {c.caseNumber}
                    </Link>
                  </td>
                  <td>
                    <div className="stack">
                      <span className="truncate">
                        {c.meta.customer || c.meta.subject || <span className="muted">Ukjent</span>}
                      </span>
                      {c.meta.customer && c.meta.subject && (
                        <span className="muted truncate" style={{ fontSize: 12 }}>
                          {c.meta.subject}
                        </span>
                      )}
                      {c.awaitingNote && (
                        <span className="muted truncate" style={{ fontSize: 12, fontStyle: "italic" }}>
                          Venter på: {c.awaitingNote}
                        </span>
                      )}
                    </div>
                  </td>
                  <td><StatusBadge status={c.meta.status} /></td>
                  <td title={formatDateTime(c.awaitingSince)}>
                    {isStale ? (
                      <span className="badge badge-amber">{formatRelative(c.awaitingSince)}</span>
                    ) : (
                      <span className="dim">{formatRelative(c.awaitingSince)}</span>
                    )}
                  </td>
                  <td>
                    <Link
                      href={`/cases/${c.caseNumber}`}
                      className="btn btn-ghost"
                      style={{ padding: "4px 9px" }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <IconExternal width={14} height={14} /> Åpne
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
