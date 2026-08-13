// Shared types for the Auto-XSALE frontend.

export type FileKind = "markdown" | "json" | "csv" | "text" | "image" | "binary";

export interface CaseFile {
  name: string;
  kind: FileKind;
  size: number;
  modified: string; // ISO
  /**
   * Only meaningful for `kind: "image"`. False for formats the browser cannot
   * paint (HEIC, TIFF) — those get a download link instead of a broken icon.
   */
  displayable?: boolean;
}

/** Lightweight metadata parsed from case_raw.json when available. */
export interface CaseMeta {
  subject: string | null;
  customer: string | null;
  status: string | null; // XSALE status, e.g. NEW / IN_PROGRESS
  priority: string | null; // e.g. HIGH
  origin: string | null; // e.g. EMAIL
  created: string | null;
  updated: string | null;
}

/**
 * Where a case sits in the user's own workflow, independent of its XSALE status.
 *   open     — not touched in the app yet
 *   awaiting — answered, now waiting for the customer to come back
 *   resolved — actually finished
 */
export type WorkState = "open" | "awaiting" | "resolved";

export interface CaseSummary {
  caseNumber: string;
  path: string;
  processed: boolean;
  workState: WorkState;
  resolved: boolean; // user marked the case as handled/answered
  resolvedAt: string | null; // ISO timestamp of when it was marked resolved
  awaiting: boolean; // waiting for customer feedback
  awaitingSince: string | null; // ISO timestamp of when it was parked
  awaitingNote: string | null; // optional note on what we are waiting for
  files: string[];
  fileCount: number;
  lastModified: string; // ISO — most recent mtime in the folder
  hasTroubleshooting: boolean;
  hasDraftReply: boolean;
  meta: CaseMeta;
}

export interface CaseDetail extends CaseSummary {
  fileDetails: CaseFile[];
}

export interface FileContent {
  name: string;
  kind: FileKind;
  size: number;
  modified: string;
  content: string | null; // null for images and binaries
  /** MIME type, for images and downloads. */
  mime?: string;
  /** See CaseFile.displayable. */
  displayable?: boolean;
  /**
   * Set when a text file was too large to inline. The file is still readable
   * via the raw URL — this flags why `content` is null so the UI can say so
   * instead of claiming the file is binary.
   */
  tooLarge?: boolean;
}

export interface AgentStatus {
  state: "working" | "standby";
  lastRun: string | null;
  nextRun: string | null;
  intervalMinutes: number | null;
  lastCaseNumber: string | null;
  processedToday: number;
  processedThisWeek: number;
  totalProcessed: number;
  source: "status-file" | "derived";
}

export interface AssignedCase {
  caseNumber: string;
  customer: string | null;
  subject: string | null;
  status: string | null;
  priority: string | null;
  created: string | null;
  processed: boolean; // has a local processed case folder
  workState: WorkState;
  resolved: boolean; // user marked the case as handled/answered
  awaiting: boolean; // waiting for customer feedback
  hasLocalFolder: boolean;
  source: "local-snapshot" | "mock";
}
