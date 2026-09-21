"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CaseFile, FileContent } from "@/lib/types";
import { formatBytes } from "@/lib/format";
import { rawFileUrl } from "@/lib/files";
import {
  IconCopy,
  IconCheck,
  IconDownload,
  IconFile,
  IconGrid,
  IconImage,
  IconList,
  IconMaximize,
} from "../../components/Icons";
import Gallery from "./Gallery";
import ImageLightbox from "./ImageLightbox";

// Friendly labels + ordering for the known agent deliverables.
const ORDER: Record<string, number> = {
  "troubleshooting.md": 1,
  "draft_reply.md": 2,
  "db_findings.md": 3,
  "internal_checklist.md": 4,
  "case_raw.json": 9,
};
const LABELS: Record<string, string> = {
  "troubleshooting.md": "Analyse",
  "draft_reply.md": "Svarutkast",
  "db_findings.md": "DB-funn",
  "internal_checklist.md": "Sjekkliste",
  "case_raw.json": "Rådata (XSALE)",
};

/**
 * Datostemplede filer fra oppfølgingsrunden. `draft_reply.md` og
 * `troubleshooting.md` overskrives aldri — nye funn og nye utkast kommer som
 * egne filer med dato, så de må gjenkjennes på prefiks framfor eksakt navn.
 */
const DATED: Array<{ prefix: string; label: string; order: number }> = [
  { prefix: "draft_reply_", label: "Svarutkast", order: 2.5 },
  { prefix: "oppfolging_", label: "Oppfølging", order: 2.8 },
];

function datedMatch(name: string) {
  return DATED.find((d) => name.startsWith(d.prefix) && name.endsWith(".md"));
}

/** Trekk ut datoen så den kan vises ved siden av etiketten. */
function datedSuffix(name: string, prefix: string): string {
  return name.slice(prefix.length).replace(/\.md$/, "").replace(/_/g, " ");
}

function labelOf(f: CaseFile): string {
  const known = LABELS[f.name];
  if (known) return known;
  const d = datedMatch(f.name);
  if (d) return `${d.label} ${datedSuffix(f.name, d.prefix)}`;
  return f.name;
}

/** Documents first, then loose files, then attachments — photos read last. */
function orderOf(f: CaseFile): number {
  const known = ORDER[f.name];
  if (known !== undefined) return known;
  const d = datedMatch(f.name);
  if (d) return d.order;
  return f.kind === "image" ? 6 : 5;
}

function sortFiles(files: CaseFile[]): CaseFile[] {
  return [...files].sort((a, b) => {
    const oa = orderOf(a);
    const ob = orderOf(b);
    if (oa !== ob) return oa - ob;
    return a.name.localeCompare(b.name, "nb");
  });
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; }
        else inQuotes = false;
      } else cell += ch;
    } else if (ch === '"') inQuotes = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === ";") { row.push(cell); cell = ""; }
    else if (ch === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
    else if (ch === "\r") { /* skip */ }
    else cell += ch;
  }
  if (cell.length || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ""));
}

export default function FileViewer({
  caseNumber,
  files,
  initial,
}: {
  caseNumber: string;
  files: CaseFile[];
  initial: string | null;
}) {
  const sorted = useMemo(() => sortFiles(files), [files]);
  const images = useMemo(() => sorted.filter((f) => f.kind === "image"), [sorted]);

  const [view, setView] = useState<"files" | "gallery">("files");
  const [active, setActive] = useState<string | null>(initial);
  const [content, setContent] = useState<FileContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);

  const load = useCallback(
    async (name: string) => {
      setLoading(true);
      setContent(null);
      try {
        const res = await fetch(
          `/api/cases/${caseNumber}/files/${encodeURIComponent(name)}`,
          { cache: "no-store" },
        );
        if (res.ok) setContent(await res.json());
      } finally {
        setLoading(false);
      }
    },
    [caseNumber],
  );

  useEffect(() => {
    if (active) load(active);
  }, [active, load]);

  const copy = async () => {
    if (!content?.content) return;
    await navigator.clipboard.writeText(content.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  /** Open the lightbox at whichever image this filename is. */
  const openLightbox = useCallback(
    (name: string) => {
      const i = images.findIndex((f) => f.name === name);
      if (i >= 0) setLightbox(i);
    },
    [images],
  );

  // Keep the selected file in step with the lightbox, so closing it leaves the
  // sidebar pointing at the photo that was last on screen.
  const onLightboxIndexChange = useCallback(
    (next: number) => {
      setLightbox(next);
      const name = images[next]?.name;
      if (name) setActive(name);
    },
    [images],
  );

  return (
    <>
      {images.length > 0 && (
        <div className="view-tabs">
          <button
            className={`view-tab ${view === "files" ? "active" : ""}`}
            onClick={() => setView("files")}
          >
            <IconList width={15} height={15} />
            Filer
            <span className="vt-count">{sorted.length}</span>
          </button>
          <button
            className={`view-tab ${view === "gallery" ? "active" : ""}`}
            onClick={() => setView("gallery")}
          >
            <IconGrid width={15} height={15} />
            Galleri
            <span className="vt-count">{images.length}</span>
          </button>
        </div>
      )}

      {view === "gallery" ? (
        <div className="panel panel-pad">
          <Gallery
            caseNumber={caseNumber}
            images={images}
            onOpen={(i) => {
              setLightbox(i);
              const name = images[i]?.name;
              if (name) setActive(name);
            }}
          />
        </div>
      ) : (
        <div className="detail-layout">
          <div className="panel file-list">
            {sorted.map((f) => (
              <button
                key={f.name}
                className={`file-item ${active === f.name ? "active" : ""}`}
                onClick={() => setActive(f.name)}
              >
                {f.kind === "image" && f.displayable !== false ? (
                  /* eslint-disable-next-line @next/next/no-img-element */
                  <img
                    className="fi-thumb"
                    src={rawFileUrl(caseNumber, f.name)}
                    alt=""
                    loading="lazy"
                    decoding="async"
                  />
                ) : f.kind === "image" ? (
                  <IconImage width={15} height={15} style={{ flexShrink: 0, opacity: 0.7 }} />
                ) : (
                  <IconFile width={15} height={15} style={{ flexShrink: 0, opacity: 0.7 }} />
                )}
                <span className="fi-name" title={f.name}>
                  {labelOf(f)}
                </span>
                <span className="fi-meta">{formatBytes(f.size)}</span>
              </button>
            ))}
            {sorted.length === 0 && (
              <div className="muted" style={{ padding: 14 }}>Ingen filer.</div>
            )}
          </div>

          <div className="panel viewer">
            <div className="viewer-head">
              <div className="row" style={{ gap: 10 }}>
                <span className="viewer-title">{active ?? "Velg en fil"}</span>
                {content && <span className="file-kind-tag">{content.kind}</span>}
              </div>
              <div className="row" style={{ gap: 8 }}>
                {content?.kind === "image" && content.displayable !== false && (
                  <button className="btn btn-ghost" onClick={() => openLightbox(content.name)}>
                    <IconMaximize width={15} height={15} />
                    Full skjerm
                  </button>
                )}
                {content && content.content == null && (
                  <a
                    className="btn btn-ghost"
                    href={rawFileUrl(caseNumber, content.name, { download: true })}
                    download={content.name}
                  >
                    <IconDownload width={15} height={15} />
                    Last ned
                  </a>
                )}
                {content?.content && (
                  <button className="btn btn-ghost" onClick={copy}>
                    {copied ? <IconCheck width={15} height={15} /> : <IconCopy width={15} height={15} />}
                    {copied ? "Kopiert" : "Kopier"}
                  </button>
                )}
              </div>
            </div>

            <div className="viewer-body">
              {!active && (
                <div className="empty">
                  <div className="big">Velg en fil til venstre</div>
                  <div className="muted">
                    Markdown rendres pent, JSON formateres, CSV vises som tabell, bilder kan zoomes.
                  </div>
                </div>
              )}
              {loading && <div className="loading">Laster…</div>}
              {!loading && content && (
                <FileBody
                  caseNumber={caseNumber}
                  content={content}
                  onExpand={() => openLightbox(content.name)}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {lightbox !== null && images.length > 0 && (
        <ImageLightbox
          caseNumber={caseNumber}
          images={images}
          index={Math.min(lightbox, images.length - 1)}
          onIndexChange={onLightboxIndexChange}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}

function FileBody({
  caseNumber,
  content,
  onExpand,
}: {
  caseNumber: string;
  content: FileContent;
  onExpand: () => void;
}) {
  if (content.kind === "image") {
    return (
      <ImagePane caseNumber={caseNumber} content={content} onExpand={onExpand} />
    );
  }

  if (content.tooLarge) {
    return (
      <div className="empty">
        <div className="big">Filen er for stor for visning</div>
        <div className="muted">
          {content.name} · {formatBytes(content.size)} — last den ned for å åpne den lokalt.
        </div>
      </div>
    );
  }

  if (content.kind === "binary" || content.content == null) {
    return (
      <div className="empty">
        <div className="big">Binær fil</div>
        <div className="muted">
          {content.name} · {formatBytes(content.size)} — kan ikke vises i nettleseren.
        </div>
      </div>
    );
  }

  if (content.kind === "markdown") {
    return (
      <div className="md">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content.content}</ReactMarkdown>
      </div>
    );
  }

  if (content.kind === "csv") {
    const rows = parseCsv(content.content);
    if (rows.length === 0) return <pre className="code">{content.content}</pre>;
    const [head, ...body] = rows;
    return (
      <div className="table-wrap">
        <table className="csv-table">
          <thead>
            <tr>{head.map((h, i) => <th key={i}>{h}</th>)}</tr>
          </thead>
          <tbody>
            {body.map((r, i) => (
              <tr key={i}>
                {head.map((_, j) => <td key={j}>{r[j] ?? ""}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  // json + text
  return <pre className="code">{content.content}</pre>;
}

function ImagePane({
  caseNumber,
  content,
  onExpand,
}: {
  caseNumber: string;
  content: FileContent;
  onExpand: () => void;
}) {
  const [failed, setFailed] = useState(false);

  // A fresh file means a fresh attempt — otherwise one broken photo makes every
  // later selection look broken too.
  useEffect(() => { setFailed(false); }, [content.name]);

  if (content.displayable === false || failed) {
    return (
      <div className="empty">
        <div className="big">Kan ikke vises i nettleseren</div>
        <div className="muted">
          {content.name} · {formatBytes(content.size)}
          {content.displayable === false && " · formatet støttes ikke av nettlesere"}
        </div>
        <a
          className="btn btn-primary"
          style={{ marginTop: 16 }}
          href={rawFileUrl(caseNumber, content.name, { download: true })}
          download={content.name}
        >
          <IconDownload width={16} height={16} />
          Last ned filen
        </a>
      </div>
    );
  }

  return (
    <div className="img-pane">
      <button className="img-pane-frame" onClick={onExpand} title="Klikk for full skjerm">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={rawFileUrl(caseNumber, content.name)}
          alt={content.name}
          onError={() => setFailed(true)}
        />
        <span className="img-pane-hint">
          <IconMaximize width={15} height={15} />
          Klikk for å zoome
        </span>
      </button>
    </div>
  );
}
