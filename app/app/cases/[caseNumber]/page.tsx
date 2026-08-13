import Link from "next/link";
import { notFound } from "next/navigation";
import { getCaseDetail } from "@/lib/cases";
import { formatDateTime } from "@/lib/format";
import { PriorityBadge, ProcessedBadge, StatusBadge } from "../../components/Badge";
import { IconChevron } from "../../components/Icons";
import FileViewer from "./FileViewer";
import ResolveButton from "./ResolveButton";

export const dynamic = "force-dynamic";

export default async function CaseDetailPage({
  params,
}: {
  params: { caseNumber: string };
}) {
  const detail = await getCaseDetail(params.caseNumber);
  if (!detail) notFound();

  const initial =
    detail.files.find((f) => f === "troubleshooting.md") ??
    detail.files.find((f) => f === "draft_reply.md") ??
    detail.fileDetails[0]?.name ??
    null;

  const m = detail.meta;

  return (
    <>
      <div className="row" style={{ gap: 6, marginBottom: 14, fontSize: 13 }}>
        <Link href="/cases" className="muted">Behandlede saker</Link>
        <IconChevron width={14} height={14} style={{ opacity: 0.5 }} />
        <span className="case-num">{detail.caseNumber}</span>
      </div>

      <div className="page-head" style={{ marginBottom: 16 }}>
        <div>
          <h1 className="page-title">
            <span className="case-num" style={{ fontSize: 22 }}>{detail.caseNumber}</span>
            {m.customer && <span style={{ marginLeft: 12 }}>{m.customer}</span>}
          </h1>
          {m.subject && <p className="page-subtitle">{m.subject}</p>}
        </div>
        <div className="row">
          {detail.resolved && (
            <span className="badge badge-green" title="Markert som løst">
              <span className="dot" />
              Løst
            </span>
          )}
          <ProcessedBadge processed={detail.processed} />
          <StatusBadge status={m.status} />
          <PriorityBadge priority={m.priority} />
        </div>
      </div>

      {/* Resolve action bar */}
      <div className="panel panel-pad row spread" style={{ marginBottom: 18, padding: "14px 20px" }}>
        <div className="dim" style={{ fontSize: 13 }}>
          {detail.workState === "resolved"
            ? "Denne saken er markert som løst og ligger under «Løste saker»."
            : detail.workState === "awaiting"
              ? detail.awaitingNote
                ? `Venter på tilbakemelding: ${detail.awaitingNote}`
                : "Denne saken venter på tilbakemelding fra kunden og ligger under «Venter på svar»."
              : "Ferdig med saken? Marker den som løst. Venter du på kunden, park den i stedet."}
        </div>
        <ResolveButton
          caseNumber={detail.caseNumber}
          workState={detail.workState}
          resolvedAt={detail.resolvedAt}
          awaitingSince={detail.awaitingSince}
          awaitingNote={detail.awaitingNote}
        />
      </div>

      {/* Metadata strip */}
      <div className="panel panel-pad" style={{ marginBottom: 18 }}>
        <div className="meta-grid">
          <div className="meta-item">
            <div className="k">Opprettet</div>
            <div className="v">{formatDateTime(m.created)}</div>
          </div>
          <div className="meta-item">
            <div className="k">Oppdatert i XSALE</div>
            <div className="v">{formatDateTime(m.updated)}</div>
          </div>
          <div className="meta-item">
            <div className="k">Sist endret lokalt</div>
            <div className="v">{formatDateTime(detail.lastModified)}</div>
          </div>
          <div className="meta-item">
            <div className="k">Opprinnelse</div>
            <div className="v">{m.origin || "–"}</div>
          </div>
          <div className="meta-item">
            <div className="k">Antall filer</div>
            <div className="v">{detail.fileCount}</div>
          </div>
        </div>
        <div className="divider" style={{ margin: "14px 0 12px" }} />
        <div className="meta-item">
          <div className="k">Lokal mappe</div>
          <div className="v mono" style={{ fontSize: 12.5, color: "var(--text-dim)" }}>
            {detail.path}
          </div>
        </div>
      </div>

      <FileViewer
        caseNumber={detail.caseNumber}
        files={detail.fileDetails}
        initial={initial}
      />
    </>
  );
}
