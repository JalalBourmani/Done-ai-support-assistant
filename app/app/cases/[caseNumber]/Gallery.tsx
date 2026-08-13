"use client";

import { useState } from "react";
import type { CaseFile } from "@/lib/types";
import { formatBytes } from "@/lib/format";
import { rawFileUrl } from "@/lib/files";
import { IconImage, IconMaximize } from "../../components/Icons";

/**
 * Thumbnail grid for a case folder's images.
 *
 * The full-size file is used as the thumbnail source. That is fine here: this
 * is a local tool reading a local disk, and generating a thumbnail cache would
 * mean writing into the user's case folders, which the app deliberately never does.
 */
export default function Gallery({
  caseNumber,
  images,
  onOpen,
}: {
  caseNumber: string;
  images: CaseFile[];
  onOpen: (index: number) => void;
}) {
  const [failed, setFailed] = useState<Record<string, boolean>>({});

  if (images.length === 0) {
    return (
      <div className="empty">
        <div className="big">Ingen bilder i denne saken</div>
        <div className="muted">Legg bildefiler i saksmappen, så vises de her.</div>
      </div>
    );
  }

  return (
    <div className="gallery">
      {images.map((img, i) => {
        const broken = failed[img.name] || img.displayable === false;
        return (
          <button
            key={img.name}
            className="thumb"
            onClick={() => onOpen(i)}
            title={`${img.name} · ${formatBytes(img.size)}`}
          >
            <div className="thumb-frame">
              {broken ? (
                <div className="thumb-fallback">
                  <IconImage width={26} height={26} style={{ opacity: 0.45 }} />
                  <span>Kan ikke forhåndsvises</span>
                </div>
              ) : (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={rawFileUrl(caseNumber, img.name)}
                    alt={img.name}
                    loading="lazy"
                    decoding="async"
                    onError={() => setFailed((f) => ({ ...f, [img.name]: true }))}
                  />
                  <span className="thumb-zoom">
                    <IconMaximize width={16} height={16} />
                  </span>
                </>
              )}
            </div>
            <div className="thumb-meta">
              <span className="tm-name" title={img.name}>{img.name}</span>
              <span className="tm-size">{formatBytes(img.size)}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
