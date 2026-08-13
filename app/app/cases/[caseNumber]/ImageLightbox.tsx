"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { CaseFile } from "@/lib/types";
import { formatBytes } from "@/lib/format";
import { rawFileUrl } from "@/lib/files";
import {
  IconArrowLeft,
  IconArrowRight,
  IconClose,
  IconDownload,
  IconRotate,
  IconZoomIn,
  IconZoomOut,
} from "../../components/Icons";

const MIN_SCALE = 1;
const MAX_SCALE = 10;
/** Scale a double-click jumps to — enough to read a serial number off a photo. */
const DOUBLE_CLICK_SCALE = 3;

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export default function ImageLightbox({
  caseNumber,
  images,
  index,
  onIndexChange,
  onClose,
}: {
  caseNumber: string;
  images: CaseFile[];
  index: number;
  onIndexChange: (next: number) => void;
  onClose: () => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  /**
   * scale/tx/ty move together — every zoom has to adjust the offset in the same
   * step to keep a point fixed. Splitting them into separate useState calls
   * meant updating one from inside another's updater, which React is free to
   * run twice (and does, under StrictMode), doubling every pan.
   */
  const [zoom, setZoom] = useState({ scale: 1, tx: 0, ty: 0 });
  const { scale, tx, ty } = zoom;
  const [rot, setRot] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, tx: 0, ty: 0 });
  const draggingRef = useRef(false);

  const current = images[index];

  const reset = useCallback(() => {
    setZoom({ scale: 1, tx: 0, ty: 0 });
    setRot(0);
  }, []);

  // A new image should never inherit the previous one's zoom or rotation.
  useEffect(() => {
    reset();
    setLoaded(false);
    setFailed(false);
    // Blading with the arrow keys mid-drag would otherwise leave the new image
    // stuck in drag mode with a stale origin.
    draggingRef.current = false;
    setDragging(false);
  }, [current?.name, reset]);

  const go = useCallback(
    (delta: number) => {
      if (images.length < 2) return;
      const next = (index + delta + images.length) % images.length;
      onIndexChange(next);
    },
    [index, images.length, onIndexChange],
  );

  /** Zoom while keeping the point under (cx, cy) — stage-centre relative — fixed. */
  const zoomAt = useCallback((factor: number, cx = 0, cy = 0) => {
    setZoom((prev) => {
      const next = clamp(prev.scale * factor, MIN_SCALE, MAX_SCALE);
      if (next === prev.scale) return prev;
      // Fully zoomed out always means centred, otherwise the image can end up
      // parked off-screen with no way to drag it back.
      if (next === MIN_SCALE) return { scale: next, tx: 0, ty: 0 };
      const k = next / prev.scale;
      return {
        scale: next,
        tx: cx - k * (cx - prev.tx),
        ty: cy - k * (cy - prev.ty),
      };
    });
  }, []);

  // Wheel must be a non-passive listener or preventDefault() is ignored and the
  // page scrolls behind the overlay while zooming.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = stage.getBoundingClientRect();
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      zoomAt(Math.exp(-e.deltaY * 0.0018), cx, cy);
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      switch (e.key) {
        case "Escape": onClose(); break;
        case "ArrowRight": go(1); break;
        case "ArrowLeft": go(-1); break;
        case "+": case "=": zoomAt(1.3); break;
        case "-": zoomAt(1 / 1.3); break;
        case "r": case "R": setRot((r) => (r + 90) % 360); break;
        case "0": reset(); break;
        default: return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose, reset, zoomAt]);

  // Stop the page behind the overlay from scrolling.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);

  if (!current) return null;

  const src = rawFileUrl(caseNumber, current.name);
  const prevSrc = images.length > 1
    ? rawFileUrl(caseNumber, images[(index - 1 + images.length) % images.length].name)
    : null;
  const nextSrc = images.length > 1
    ? rawFileUrl(caseNumber, images[(index + 1) % images.length].name)
    : null;

  const onPointerDown = (e: React.PointerEvent) => {
    if (scale <= 1) return;
    // Capture is a nicety — it keeps the drag alive when the cursor leaves the
    // stage. If the browser refuses (pointer already gone), drag anyway rather
    // than throwing out of the handler and never starting.
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* no capture available; plain drag still works */
    }
    dragStart.current = { x: e.clientX, y: e.clientY, tx, ty };
    // A ref, not just state: the first pointermove can arrive before React has
    // re-rendered with `dragging: true`, and dropping it makes the image jump.
    draggingRef.current = true;
    setDragging(true);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    setZoom((z) => ({
      ...z,
      tx: dragStart.current.tx + dx,
      ty: dragStart.current.ty + dy,
    }));
  };

  const endDrag = (e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* capture was never taken */
    }
    draggingRef.current = false;
    setDragging(false);
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    const stage = stageRef.current;
    if (!stage) return;
    const rect = stage.getBoundingClientRect();
    const cx = e.clientX - rect.left - rect.width / 2;
    const cy = e.clientY - rect.top - rect.height / 2;
    if (scale > 1) reset();
    else zoomAt(DOUBLE_CLICK_SCALE, cx, cy);
  };

  return (
    <div className="lb" role="dialog" aria-modal="true" aria-label={current.name}>
      <div className="lb-bar">
        <div className="lb-meta">
          <span className="lb-name">{current.name}</span>
          <span className="lb-sub">
            {images.length > 1 && `${index + 1} / ${images.length} · `}
            {formatBytes(current.size)}
            {scale !== 1 && ` · ${Math.round(scale * 100)} %`}
          </span>
        </div>
        <div className="lb-tools">
          <button className="lb-btn" onClick={() => zoomAt(1 / 1.4)} title="Zoom ut (−)" aria-label="Zoom ut">
            <IconZoomOut width={17} height={17} />
          </button>
          <button className="lb-btn" onClick={() => zoomAt(1.4)} title="Zoom inn (+)" aria-label="Zoom inn">
            <IconZoomIn width={17} height={17} />
          </button>
          <button className="lb-btn" onClick={() => setRot((r) => (r + 90) % 360)} title="Roter (R)" aria-label="Roter">
            <IconRotate width={17} height={17} />
          </button>
          <button className="lb-btn" onClick={reset} title="Tilbakestill (0)">100 %</button>
          <a
            className="lb-btn"
            href={rawFileUrl(caseNumber, current.name, { download: true })}
            download={current.name}
            title="Last ned"
            aria-label="Last ned"
          >
            <IconDownload width={17} height={17} />
          </a>
          <button className="lb-btn lb-close" onClick={onClose} title="Lukk (Esc)" aria-label="Lukk">
            <IconClose width={18} height={18} />
          </button>
        </div>
      </div>

      <div
        className="lb-stage"
        ref={stageRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={onDoubleClick}
        style={{ cursor: scale > 1 ? (dragging ? "grabbing" : "grab") : "zoom-in" }}
      >
        {!loaded && !failed && <div className="lb-loading">Laster bilde…</div>}
        {failed ? (
          <div className="lb-failed">
            <div className="big">Kan ikke vises i nettleseren</div>
            <div className="muted">
              {current.name} · {formatBytes(current.size)}
            </div>
            <a
              className="btn btn-primary"
              style={{ marginTop: 16 }}
              href={rawFileUrl(caseNumber, current.name, { download: true })}
              download={current.name}
            >
              <IconDownload width={16} height={16} />
              Last ned filen
            </a>
          </div>
        ) : (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            className="lb-img"
            src={src}
            alt={current.name}
            draggable={false}
            onLoad={() => setLoaded(true)}
            onError={() => { setFailed(true); setLoaded(true); }}
            style={{
              transform: `translate(${tx}px, ${ty}px) scale(${scale}) rotate(${rot}deg)`,
              transition: dragging ? "none" : "transform 0.12s ease-out",
              opacity: loaded ? 1 : 0,
            }}
          />
        )}
      </div>

      {images.length > 1 && (
        <>
          <button className="lb-nav prev" onClick={() => go(-1)} title="Forrige (←)" aria-label="Forrige bilde">
            <IconArrowLeft width={22} height={22} />
          </button>
          <button className="lb-nav next" onClick={() => go(1)} title="Neste (→)" aria-label="Neste bilde">
            <IconArrowRight width={22} height={22} />
          </button>
        </>
      )}

      <div className="lb-hint">
        Rull for å zoome · dra for å flytte · dobbeltklikk for full zoom · ← → for å bla · Esc lukker
      </div>

      {/* Warm the browser cache for the neighbours so blading is instant. */}
      <div style={{ display: "none" }} aria-hidden="true">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {prevSrc && <img src={prevSrc} alt="" />}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {nextSrc && <img src={nextSrc} alt="" />}
      </div>
    </div>
  );
}
