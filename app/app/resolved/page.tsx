import { getResolvedCases } from "@/lib/cases";
import ResolvedTable from "./ResolvedTable";

export const dynamic = "force-dynamic";

export default async function ResolvedPage() {
  const cases = await getResolvedCases();

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Løste saker</h1>
          <p className="page-subtitle">
            Saker du har markert som løst · {cases.length} totalt
          </p>
        </div>
      </div>

      {cases.length === 0 ? (
        <div className="panel empty">
          <div className="big">Ingen løste saker ennå</div>
          <p className="muted">
            Når du markerer en sak som løst inne på saken, dukker den opp her.
          </p>
        </div>
      ) : (
        <ResolvedTable cases={cases} />
      )}
    </>
  );
}
