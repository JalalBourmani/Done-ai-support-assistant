import { getAwaitingCases } from "@/lib/cases";
import AwaitingTable from "./AwaitingTable";

export const dynamic = "force-dynamic";

export default async function AwaitingPage() {
  const cases = await getAwaitingCases();

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Venter på svar</h1>
          <p className="page-subtitle">
            Saker du har svart ut, men som ikke er ferdige · {cases.length} totalt
          </p>
        </div>
      </div>

      {cases.length === 0 ? (
        <div className="panel empty">
          <div className="big">Ingen saker venter på svar</div>
          <p className="muted">
            Har du svart kunden men ikke fått tilbakemelding? Park saken som
            «Venter på tilbakemelding» inne på saken, i stedet for å markere den
            som løst.
          </p>
        </div>
      ) : (
        <AwaitingTable cases={cases} />
      )}
    </>
  );
}
