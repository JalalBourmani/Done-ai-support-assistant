"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { CaseSummary } from "@/lib/types";
import { formatDateTime, formatRelative } from "@/lib/format";
import { ProcessedBadge, StatusBadge } from "../components/Badge";

const REQUIRED = ["troubleshooting.md", "draft_reply.md"];

type Filter = "all" | "processed" | "unprocessed";

export default function CasesTable({ cases }: { cases: CaseSummary[] }) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return cases.filter((c) => {
      if (filter === "processed" && !c.processed) return false;
      if (filter === "unprocessed" && c.processed) return false;
      if (!needle) return true;
      return (
        c.caseNumber.includes(needle) ||
        (c.meta.customer || "").toLowerCase().includes(needle) ||
        (c.meta.subject || "").toLowerCase().includes(needle)
      );
    });
  }, [cases, q, filter]);

  const counts = {
    all: cases.length,
    processed: cases.filter((c) => c.processed).length,
    unprocessed: cases.filter((c) => !c.processed).length,
  };

  return (
    <div className="panel">
      <div className="panel-head" style={{ gap: 12, flexWrap: "wrap" }}>
        <div className="btn-row">
          {(["all", "processed", "unprocessed"] as Filter[]).map((f) => (
            <button
              key={f}
              className={`btn ${filter === f ? "btn-primary" : "btn-ghost"}`}
              onClick={() => setFilter(f)}
            >
              {f === "all" ? "Alle" : f === "processed" ? "Behandlet" : "Ubehandlet"}
              <span style={{ opacity: 0.7 }}>{counts[f]}</span>
            </button>
          ))}
        </div>
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
              <th>Filer</th>
              <th>Behandlet</th>
              <th>Sist endret</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="muted" style={{ textAlign: "center", padding: 30 }}>
                  Ingen saker matcher.
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
                <td>
                  <div className="chips" style={{ maxWidth: 280 }}>
                    {c.files.slice(0, 5).map((f) => (
                      <span
                        key={f}
                        className={`chip ${REQUIRED.includes(f) ? "req" : ""}`}
                        title={f}
                      >
                        {f}
                      </span>
                    ))}
                    {c.files.length > 5 && (
                      <span className="chip">+{c.files.length - 5}</span>
                    )}
                  </div>
                </td>
                <td><ProcessedBadge processed={c.processed} /></td>
                <td className="dim" title={formatDateTime(c.lastModified)}>
                  {formatRelative(c.lastModified)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
