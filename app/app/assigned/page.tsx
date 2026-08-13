import { getAssignedCases } from "@/lib/cases";
import AssignedTable from "./AssignedTable";

export const dynamic = "force-dynamic";

export default async function AssignedPage() {
  const cases = await getAssignedCases();
  const open = cases.filter((c) => !c.processed).length;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Mine XSALE-saker</h1>
          <p className="page-subtitle">
            Saker satt på deg · {open} gjenstår av {cases.length}
          </p>
        </div>
        <span className="badge badge-blue" title="Bygget fra lokale case_raw.json. Bytt til live XSALE MCP/API i /api/assigned-cases.">
          <span className="dot" />
          Kilde: lokalt øyeblikksbilde
        </span>
      </div>

      {cases.length === 0 ? (
        <div className="panel empty">
          <div className="big">Ingen tildelte saker funnet</div>
          <p className="muted">
            Når XSALE-MCP/API kobles til, hentes aktive saker live. Nå bygges listen
            fra <code>case_raw.json</code> i de lokale saksmappene.
          </p>
        </div>
      ) : (
        <AssignedTable cases={cases} />
      )}
    </>
  );
}
