"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { CaseSummary } from "@/lib/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { StatusBadge } from "../components/Badge";
import { IconExternal } from "../components/Icons";

export default function ResolvedTable({ cases }: { cases: CaseSummary[] }) {
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return cases;
    return cases.filter(
      (c) =>
        c.caseNumber.includes(needle) ||
        (c.meta.customer || "").toLowerCase().includes(needle) ||
        (c.meta.subject || "").toLowerCase().includes(needle),
    );
  }, [cases, q]);

  return (
    <div className="panel">
      <div className="panel-head" style={{ gap: 12, flexWrap: "wrap" }}>
        <h2>{cases.length} løste saker</h2>
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
              <th>Status</th>
              <th>Løst</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="muted" style={{ textAlign: "center", padding: 30 }}>
                  Ingen løste saker {q ? "matcher søket" : "ennå"}.
                </td>
              </tr>
            )}
            {rows.map((c) => (
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
                  </div>
                </td>
                <td><StatusBadge status={c.meta.status} /></td>
                <td className="dim" title={formatDateTime(c.resolvedAt)}>
                  {formatRelative(c.resolvedAt)}
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
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
