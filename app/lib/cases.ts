import fs from "node:fs/promises";
import { Dirent } from "node:fs";
import path from "node:path";
import {
  AgentStatus,
  AssignedCase,
  CaseDetail,
  CaseFile,
  CaseMeta,
  CaseSummary,
  FileContent,
} from "./types";
import { deriveWorkState, getAwaitingMap, getResolvedMap } from "./store";
import { isDisplayableImage, kindForFile, mimeForFile } from "./files";

type AwaitingMap = Record<string, { since: string; note: string | null }>;

// --- Configuration -------------------------------------------------------

/**
 * Root folder where the agent writes case sub-folders.
 *
 * No fallback on purpose. A hardcoded default pointing at one developer's home
 * directory silently resolves to a folder that does not exist on anyone else's
 * machine — and `listCaseNumbers()` swallows the resulting ENOENT and returns an
 * empty array, so a misconfigured install looks exactly like a quiet week.
 * Failing here names the problem instead.
 */
export function getRootDir(): string {
  const dir = process.env.AUTO_XSALE_DIR;
  if (!dir || !dir.trim()) {
    throw new Error(
      "AUTO_XSALE_DIR er ikke satt. Opprett app/.env.local med linjen " +
        "AUTO_XSALE_DIR=<sti til saksmappen din>, eller kjør scripts\\install.ps1 " +
        "som setter den for deg.",
    );
  }
  return dir;
}

const PROCESSED_REQUIRED = ["troubleshooting.md", "draft_reply.md"];

// --- Small helpers -------------------------------------------------------

/** Resolve a file path inside a case folder, guarding against traversal. */
function safeCaseFilePath(caseNumber: string, fileName: string): string {
  const root = getRootDir();
  const caseDir = path.resolve(root, sanitizeSegment(caseNumber));
  const target = path.resolve(caseDir, sanitizeSegment(fileName));
  // Ensure the resolved target stays within the case directory.
  const rel = path.relative(caseDir, target);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error("Invalid path");
  }
  return target;
}

/** Reject anything that isn't a single, plain path segment. */
function sanitizeSegment(seg: string): string {
  if (!seg || seg.includes("/") || seg.includes("\\") || seg.includes("..")) {
    throw new Error("Invalid path segment");
  }
  return seg;
}

/**
 * Strip a UTF-8 BOM. Files in the case folders are written by the agent, but a
 * human editing one in Notepad — or any PowerShell `Set-Content -Encoding utf8`
 * — leaves a BOM behind. That breaks JSON.parse outright and stops `^#` from
 * matching an H1, in both cases silently losing the metadata rather than
 * complaining. One line here beats debugging an invisible byte later.
 */
function stripBom(s: string): string {
  return s.charCodeAt(0) === 0xfeff ? s.slice(1) : s;
}

async function safeStat(p: string) {
  try {
    return await fs.stat(p);
  } catch {
    return null;
  }
}

// --- Case discovery ------------------------------------------------------

/** List case folder names (each sub-directory of the root). */
export async function listCaseNumbers(): Promise<string[]> {
  const root = getRootDir();
  let entries: Dirent[];
  try {
    entries = await fs.readdir(root, { withFileTypes: true });
  } catch {
    return [];
  }
  return entries
    .filter((e) => e.isDirectory() && !e.name.startsWith("."))
    .map((e) => e.name)
    // Newest case numbers first (numeric desc when numeric).
    .sort((a, b) => {
      const na = Number(a);
      const nb = Number(b);
      if (!Number.isNaN(na) && !Number.isNaN(nb)) return nb - na;
      return b.localeCompare(a);
    });
}

async function readCaseFiles(caseNumber: string): Promise<CaseFile[]> {
  const root = getRootDir();
  const dir = path.join(root, caseNumber);
  let entries: Dirent[];
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return [];
  }
  const files: CaseFile[] = [];
  for (const e of entries) {
    if (!e.isFile()) continue;
    if (e.name.startsWith(".~lock")) continue; // LibreOffice lock files
    const st = await safeStat(path.join(dir, e.name));
    const kind = kindForFile(e.name);
    files.push({
      name: e.name,
      kind,
      size: st?.size ?? 0,
      modified: (st?.mtime ?? new Date(0)).toISOString(),
      ...(kind === "image" ? { displayable: isDisplayableImage(e.name) } : {}),
    });
  }
  return files.sort((a, b) => a.name.localeCompare(b.name));
}

function stripHtml(s: string): string {
  return s
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

/** Parse the slice of case_raw.json we care about, defensively. */
async function readCaseMeta(caseNumber: string): Promise<CaseMeta> {
  const empty: CaseMeta = {
    subject: null,
    customer: null,
    status: null,
    priority: null,
    origin: null,
    created: null,
    updated: null,
  };
  const file = path.join(getRootDir(), caseNumber, "case_raw.json");
  try {
    const raw = await fs.readFile(file, "utf-8");
    const d = JSON.parse(stripBom(raw));
    const customer =
      d?.customer?.name ||
      [d?.customer?.firstname, d?.customer?.lastname]
        .filter(Boolean)
        .join(" ") ||
      null;
    return {
      subject: d?.subject ? stripHtml(String(d.subject)) : null,
      customer: customer || null,
      status: d?.status ?? null,
      priority: d?.priority ?? null,
      origin: d?.origin ?? null,
      created: d?.created ?? null,
      updated: d?.updated ?? null,
    };
  } catch {
    return empty;
  }
}

/** Fall back to the H1 of troubleshooting.md for a subject when no JSON. */
async function subjectFromTroubleshooting(
  caseNumber: string,
): Promise<string | null> {
  try {
    const raw = stripBom(
      await fs.readFile(
        path.join(getRootDir(), caseNumber, "troubleshooting.md"),
        "utf-8",
      ),
    );
    const m = raw.match(/^#\s+(.+)$/m);
    return m ? m[1].trim() : null;
  } catch {
    return null;
  }
}

export async function getCaseSummary(
  caseNumber: string,
  resolvedMap?: Record<string, string>,
  awaitingMap?: AwaitingMap,
): Promise<CaseSummary | null> {
  const root = getRootDir();
  const dir = path.join(root, caseNumber);
  const st = await safeStat(dir);
  if (!st || !st.isDirectory()) return null;

  const resolved = resolvedMap ?? (await getResolvedMap());
  const awaiting = awaitingMap ?? (await getAwaitingMap());
  const resolvedAt = resolved[caseNumber] ?? null;
  const awaitingEntry = awaiting[caseNumber] ?? null;
  const workState = deriveWorkState(caseNumber, resolved, awaiting);

  const files = await readCaseFiles(caseNumber);
  const fileNames = files.map((f) => f.name);
  const has = (n: string) => fileNames.includes(n);
  const hasTroubleshooting = has("troubleshooting.md");
  const hasDraftReply = has("draft_reply.md");

  const lastModified = files.length
    ? files
        .map((f) => f.modified)
        .sort()
        .at(-1)!
    : st.mtime.toISOString();

  const meta = await readCaseMeta(caseNumber);
  if (!meta.subject) {
    meta.subject = await subjectFromTroubleshooting(caseNumber);
  }

  return {
    caseNumber,
    path: dir,
    processed: PROCESSED_REQUIRED.every((f) => has(f)),
    workState,
    resolved: resolvedAt !== null,
    resolvedAt,
    awaiting: awaitingEntry !== null,
    awaitingSince: awaitingEntry?.since ?? null,
    awaitingNote: awaitingEntry?.note ?? null,
    files: fileNames,
    fileCount: fileNames.length,
    lastModified,
    hasTroubleshooting,
    hasDraftReply,
    meta,
  };
}

export async function getAllCases(): Promise<CaseSummary[]> {
  const [numbers, resolvedMap, awaitingMap] = await Promise.all([
    listCaseNumbers(),
    getResolvedMap(),
    getAwaitingMap(),
  ]);
  const summaries = await Promise.all(
    numbers.map((n) => getCaseSummary(n, resolvedMap, awaitingMap)),
  );
  return summaries
    .filter((s): s is CaseSummary => s !== null)
    .sort((a, b) => b.lastModified.localeCompare(a.lastModified));
}

/** Cases the user has marked resolved, newest-resolved first. */
export async function getResolvedCases(): Promise<CaseSummary[]> {
  const all = await getAllCases();
  return all
    .filter((c) => c.resolved)
    .sort((a, b) => (b.resolvedAt ?? "").localeCompare(a.resolvedAt ?? ""));
}

/**
 * Cases parked while waiting for the customer. Oldest first on purpose: the
 * ones that have been waiting longest are the ones most likely to be forgotten,
 * so they belong at the top rather than buried at the bottom.
 */
export async function getAwaitingCases(): Promise<CaseSummary[]> {
  const all = await getAllCases();
  return all
    .filter((c) => c.awaiting)
    .sort((a, b) => (a.awaitingSince ?? "").localeCompare(b.awaitingSince ?? ""));
}

export async function getCaseDetail(
  caseNumber: string,
): Promise<CaseDetail | null> {
  const summary = await getCaseSummary(caseNumber);
  if (!summary) return null;
  const fileDetails = await readCaseFiles(caseNumber);
  return { ...summary, fileDetails };
}

// --- File reading --------------------------------------------------------

const MAX_TEXT_BYTES = 2 * 1024 * 1024; // 2 MB safety cap for text rendering

/** Largest file we will stream raw. Phone photos run 2–5 MB; 64 MB is ample. */
const MAX_RAW_BYTES = 64 * 1024 * 1024;

export async function readCaseFileContent(
  caseNumber: string,
  fileName: string,
): Promise<FileContent | null> {
  const target = safeCaseFilePath(caseNumber, fileName);
  const st = await safeStat(target);
  if (!st || !st.isFile()) return null;

  const kind = kindForFile(fileName);
  const base: Omit<FileContent, "content"> = {
    name: fileName,
    kind,
    size: st.size,
    modified: st.mtime.toISOString(),
    mime: mimeForFile(fileName),
  };

  // Images are described here but never inlined — the client fetches the bytes
  // from the raw endpoint, so a 3 MB photo costs one image request instead of a
  // 4 MB base64 string in a JSON payload.
  if (kind === "image") {
    return {
      ...base,
      content: null,
      displayable: isDisplayableImage(fileName),
    };
  }

  if (kind === "binary") {
    return { ...base, content: null };
  }

  // The size cap is about rendering a wall of text in the browser, so it only
  // applies to the text kinds. Applying it to everything is what used to turn
  // every photo over 2 MB into an unopenable "binary file".
  if (st.size > MAX_TEXT_BYTES) {
    return { ...base, content: null, tooLarge: true };
  }

  let content = await fs.readFile(target, "utf-8");
  if (kind === "json") {
    try {
      content = JSON.stringify(JSON.parse(content), null, 2);
    } catch {
      // leave as-is if it isn't valid JSON
    }
  }
  return { ...base, content };
}

export interface RawFile {
  name: string;
  bytes: Buffer;
  mime: string;
  size: number;
  modified: Date;
}

/**
 * Read a file's actual bytes for streaming to the browser. Shares the same
 * traversal guard as the text path — the only way into a case folder is
 * through `safeCaseFilePath`.
 */
export async function readCaseFileRaw(
  caseNumber: string,
  fileName: string,
): Promise<RawFile | null> {
  const target = safeCaseFilePath(caseNumber, fileName);
  const st = await safeStat(target);
  if (!st || !st.isFile() || st.size > MAX_RAW_BYTES) return null;

  return {
    name: fileName,
    bytes: await fs.readFile(target),
    mime: mimeForFile(fileName),
    size: st.size,
    modified: st.mtime,
  };
}

// --- Agent status --------------------------------------------------------

function startOfWeek(d: Date): Date {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Monday = 0
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() - day);
  return x;
}

export async function getAgentStatus(): Promise<AgentStatus> {
  const cases = await getAllCases();
  const processed = cases.filter((c) => c.processed);

  const now = new Date();
  const startToday = new Date(now);
  startToday.setHours(0, 0, 0, 0);
  const weekStart = startOfWeek(now);

  const processedToday = processed.filter(
    (c) => new Date(c.lastModified) >= startToday,
  ).length;
  const processedThisWeek = processed.filter(
    (c) => new Date(c.lastModified) >= weekStart,
  ).length;

  // Most recently touched case = last thing the agent worked on.
  const last = cases[0] ?? null;
  const lastRun = last?.lastModified ?? null;

  // Optional status file lets the real agent publish exact state.
  const statusFile = path.join(getRootDir(), "agent-status.json");
  let fromFile: Partial<AgentStatus> = {};
  try {
    const raw = await fs.readFile(statusFile, "utf-8");
    const d = JSON.parse(raw);
    fromFile = {
      state: d.state === "working" ? "working" : undefined,
      lastRun: d.lastRun ?? undefined,
      nextRun: d.nextRun ?? undefined,
      intervalMinutes:
        typeof d.intervalMinutes === "number" ? d.intervalMinutes : undefined,
    };
  } catch {
    // No status file — derive everything.
  }

  const intervalMinutes = fromFile.intervalMinutes ?? 30;
  const effectiveLastRun = fromFile.lastRun ?? lastRun;

  // Derive "working" if the last run was very recent (< 3 min ago).
  let state: AgentStatus["state"] = fromFile.state ?? "standby";
  if (!fromFile.state && effectiveLastRun) {
    const ageMin = (now.getTime() - new Date(effectiveLastRun).getTime()) / 60000;
    if (ageMin >= 0 && ageMin < 3) state = "working";
  }

  // Next run: from file, else last run + interval (rolled forward to future).
  let nextRun = fromFile.nextRun ?? null;
  if (!nextRun && effectiveLastRun) {
    let t = new Date(effectiveLastRun).getTime() + intervalMinutes * 60000;
    const step = intervalMinutes * 60000;
    while (t < now.getTime()) t += step;
    nextRun = new Date(t).toISOString();
  }

  return {
    state,
    lastRun: effectiveLastRun,
    nextRun,
    intervalMinutes,
    lastCaseNumber: last?.caseNumber ?? null,
    processedToday,
    processedThisWeek,
    totalProcessed: processed.length,
    source: Object.keys(fromFile).some((k) => (fromFile as any)[k] !== undefined)
      ? "status-file"
      : "derived",
  };
}

// --- Assigned cases (XSALE "Mine saker") ---------------------------------

/**
 * Cases assigned to the logged-in user in XSALE. We don't have a live MCP/API connection
 * from this UI, so we build the list from the local case_raw.json snapshots
 * the agent has already pulled. This is real data, clearly flagged as a
 * snapshot, and the shape matches what a future live XSALE API would return.
 */
export async function getAssignedCases(): Promise<AssignedCase[]> {
  const cases = await getAllCases();
  const rows: AssignedCase[] = cases
    .filter((c) => c.meta.status || c.meta.subject || c.meta.customer)
    .map((c) => ({
      caseNumber: c.caseNumber,
      customer: c.meta.customer,
      subject: c.meta.subject,
      status: c.meta.status,
      priority: c.meta.priority,
      created: c.meta.created,
      processed: c.processed,
      workState: c.workState,
      resolved: c.resolved,
      awaiting: c.awaiting,
      hasLocalFolder: true,
      source: "local-snapshot" as const,
    }));

  // Sort: newest created first, falling back to case number.
  rows.sort((a, b) => {
    if (a.created && b.created) return b.created.localeCompare(a.created);
    return Number(b.caseNumber) - Number(a.caseNumber);
  });
  return rows;
}
