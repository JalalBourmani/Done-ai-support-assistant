import { getAllCases, getRootDir } from "@/lib/cases";
import CasesTable from "./CasesTable";

export const dynamic = "force-dynamic";

export default async function CasesPage() {
  const all = await getAllCases();
  // Resolved cases move to "Løste saker" and parked ones to "Venter på svar",
  // so this list only holds what still needs attention.
  const cases = all.filter((c) => c.workState === "open");
  const resolved = all.filter((c) => c.resolved).length;
  const awaiting = all.filter((c) => c.awaiting).length;
  const processed = cases.filter((c) => c.processed).length;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Behandlede saker</h1>
          <p className="page-subtitle">
            {cases.length} aktive saksmapper · {processed} behandlet
            {awaiting > 0 ? ` · ${awaiting} venter på svar` : ""}
            {resolved > 0 ? ` · ${resolved} løst` : ""}
          </p>
        </div>
      </div>

      {all.length === 0 ? (
        <div className="panel empty">
          <div className="big">Fant ingen saksmapper</div>
          <div className="mono" style={{ fontSize: 12 }}>{getRootDir()}</div>
          <p className="muted" style={{ marginTop: 10 }}>
            Sjekk at <code>AUTO_XSALE_DIR</code> peker på riktig mappe.
          </p>
        </div>
      ) : (
        <CasesTable cases={cases} />
      )}
    </>
  );
}
