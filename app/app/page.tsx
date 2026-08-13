import Link from "next/link";
import { getAgentStatus, getAllCases, getAssignedCases } from "@/lib/cases";
import { formatDateTime, formatRelative } from "@/lib/format";
import { ProcessedBadge, StatusBadge } from "./components/Badge";
import {
  IconBolt,
  IconCheck,
  IconClock,
  IconFolder,
  IconInbox,
} from "./components/Icons";

export const dynamic = "force-dynamic";

function StatCard({
  label,
  value,
  foot,
  glow,
  Icon,
}: {
  label: string;
  value: React.ReactNode;
  foot?: React.ReactNode;
  glow?: string;
  Icon: React.ComponentType<any>;
}) {
  return (
    <div
      className="panel stat"
      style={glow ? ({ ["--glow" as any]: glow } as React.CSSProperties) : undefined}
    >
      <Icon className="stat-icon" />
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {foot && <div className="stat-foot">{foot}</div>}
    </div>
  );
}

export default async function DashboardPage() {
  const [cases, assigned, agent] = await Promise.all([
    getAllCases(),
    getAssignedCases(),
    getAgentStatus(),
  ]);

  const processed = cases.filter((c) => c.processed);
  const lastProcessed = processed[0] ?? null; // already sorted by lastModified desc
  const unprocessedAssigned = assigned.filter((a) => !a.processed);
  const working = agent.state === "working";

  const recent = processed.slice(0, 7);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Oversikt</h1>
          <p className="page-subtitle">
            Hva agenten har jobbet med, og hva som gjenstår på deg.
          </p>
        </div>
        <Link href="/agent" className="btn btn-ghost">
          <span className={`pulse ${working ? "" : "standby"}`} />
          {working ? "Agent jobber" : "Agent i standby"}
        </Link>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 18 }}>
        <StatCard
          label="XSALE-saker på deg"
          value={assigned.length}
          foot={`${unprocessedAssigned.length} gjenstår`}
          Icon={IconInbox}
          glow="rgba(56,189,248,0.35)"
        />
        <StatCard
          label="Behandlet av agenten"
          value={processed.length}
          foot={`av ${cases.length} lokale saksmapper`}
          Icon={IconCheck}
          glow="rgba(52,211,153,0.35)"
        />
        <StatCard
          label="Ubehandlet"
          value={unprocessedAssigned.length}
          foot="mangler troubleshooting/utkast"
          Icon={IconFolder}
          glow="rgba(251,191,36,0.32)"
        />
        <StatCard
          label="Behandlet denne uken"
          value={agent.processedThisWeek}
          foot={`${agent.processedToday} i dag`}
          Icon={IconBolt}
          glow="rgba(167,139,250,0.32)"
        />
      </div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(0, 1fr) 320px" }}>
        {/* Recent activity */}
        <div className="panel">
          <div className="panel-head">
            <h2>Sist behandlede saker</h2>
            <Link href="/cases" className="dim" style={{ fontSize: 12.5 }}>
              Se alle →
            </Link>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Sak</th>
                  <th>Kunde / emne</th>
                  <th>Status</th>
                  <th>Behandlet</th>
                  <th>Sist endret</th>
                </tr>
              </thead>
              <tbody>
                {recent.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted" style={{ padding: 28, textAlign: "center" }}>
                      Ingen behandlede saker funnet ennå.
                    </td>
                  </tr>
                )}
                {recent.map((c) => (
                  <tr key={c.caseNumber} className="clickable">
                    <td>
                      <Link href={`/cases/${c.caseNumber}`} className="case-num">
                        {c.caseNumber}
                      </Link>
                    </td>
                    <td>
                      <Link href={`/cases/${c.caseNumber}`} className="stack">
                        <span className="truncate">
                          {c.meta.customer || c.meta.subject || "Ukjent"}
                        </span>
                        {c.meta.customer && c.meta.subject && (
                          <span className="muted truncate" style={{ fontSize: 12 }}>
                            {c.meta.subject}
                          </span>
                        )}
                      </Link>
                    </td>
                    <td><StatusBadge status={c.meta.status} /></td>
                    <td><ProcessedBadge processed={c.processed} /></td>
                    <td className="dim" title={formatDateTime(c.lastModified)}>
                      {formatRelative(c.lastModified)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Agent + last processed side panel */}
        <div className="grid">
          <div className="panel panel-pad">
            <div className="row spread">
              <div className="stat-label">Agentstatus</div>
              <span className={`pulse ${working ? "" : "standby"}`} />
            </div>
            <div className="stat-value" style={{ fontSize: 22, marginTop: 10 }}>
              {working ? "Våken / jobber" : "Standby"}
            </div>
            <div className="divider" style={{ margin: "14px 0" }} />
            <div className="stack" style={{ gap: 12 }}>
              <div className="meta-item">
                <div className="k">
                  <IconClock width={12} height={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                  Neste kjøring
                </div>
                <div className="v">{formatDateTime(agent.nextRun)}</div>
              </div>
              <div className="meta-item">
                <div className="k">Siste kjøring</div>
                <div className="v">{formatDateTime(agent.lastRun)}</div>
              </div>
            </div>
            <Link href="/agent" className="btn btn-ghost" style={{ marginTop: 16, width: "100%", justifyContent: "center" }}>
              Åpne agent-panel
            </Link>
          </div>

          <div className="panel panel-pad">
            <div className="stat-label">Siste behandlede sak</div>
            {lastProcessed ? (
              <Link href={`/cases/${lastProcessed.caseNumber}`} className="stack" style={{ marginTop: 10, gap: 8 }}>
                <span className="case-num" style={{ fontSize: 18 }}>
                  {lastProcessed.caseNumber}
                </span>
                <span className="truncate">
                  {lastProcessed.meta.customer || lastProcessed.meta.subject || "Ukjent"}
                </span>
                <span className="muted" style={{ fontSize: 12 }}>
                  {formatRelative(lastProcessed.lastModified)}
                </span>
              </Link>
            ) : (
              <div className="muted" style={{ marginTop: 10 }}>Ingen ennå</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
