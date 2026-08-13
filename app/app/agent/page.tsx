import Link from "next/link";
import { getAgentStatus, getAllCases } from "@/lib/cases";
import { formatDateTime, formatRelative } from "@/lib/format";
import { IconBolt, IconCheck, IconClock } from "../components/Icons";

export const dynamic = "force-dynamic";

export default async function AgentPage() {
  const [agent, cases] = await Promise.all([getAgentStatus(), getAllCases()]);
  const working = agent.state === "working";
  const lastCase = cases.find((c) => c.caseNumber === agent.lastCaseNumber) ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Agent</h1>
          <p className="page-subtitle">Auto-XSALE-agentens status og aktivitet.</p>
        </div>
        <span className={`badge ${agent.source === "status-file" ? "badge-blue" : "badge-gray"}`}>
          <span className="dot" />
          {agent.source === "status-file" ? "agent-status.json" : "Avledet fra filer"}
        </span>
      </div>

      {/* Hero */}
      <div className="panel panel-pad" style={{ marginBottom: 18 }}>
        <div className="agent-hero">
          <div className={`agent-orb ${working ? "" : "standby"}`}>
            <div className="core" />
          </div>
          <div>
            <div className="row" style={{ gap: 10 }}>
              <span className={`pulse ${working ? "" : "standby"}`} />
              <span className="stat-value" style={{ fontSize: 26 }}>
                {working ? "Våken / jobber" : "Standby"}
              </span>
            </div>
            <div className="dim" style={{ marginTop: 8 }}>
              {working
                ? "Agenten behandler saker akkurat nå."
                : "Agenten venter på neste planlagte kjøring."}
            </div>
            <div className="row gap-lg" style={{ marginTop: 16 }}>
              <div className="meta-item">
                <div className="k">
                  <IconClock width={12} height={12} style={{ verticalAlign: -1, marginRight: 5 }} />
                  Neste kjøring
                </div>
                <div className="v">{formatDateTime(agent.nextRun)}</div>
              </div>
              <div className="meta-item">
                <div className="k">Siste kjøring</div>
                <div className="v">
                  {formatDateTime(agent.lastRun)}{" "}
                  <span className="muted" style={{ fontSize: 12 }}>
                    ({formatRelative(agent.lastRun)})
                  </span>
                </div>
              </div>
              {agent.intervalMinutes != null && (
                <div className="meta-item">
                  <div className="k">Intervall</div>
                  <div className="v">hvert {agent.intervalMinutes}. min</div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid stat-grid" style={{ marginBottom: 18 }}>
        <div className="panel stat" style={{ ["--glow" as any]: "rgba(52,211,153,0.32)" } as React.CSSProperties}>
          <IconCheck className="stat-icon" />
          <div className="stat-label">Behandlet i dag</div>
          <div className="stat-value">{agent.processedToday}</div>
        </div>
        <div className="panel stat" style={{ ["--glow" as any]: "rgba(167,139,250,0.32)" } as React.CSSProperties}>
          <IconBolt className="stat-icon" />
          <div className="stat-label">Behandlet denne uken</div>
          <div className="stat-value">{agent.processedThisWeek}</div>
        </div>
        <div className="panel stat" style={{ ["--glow" as any]: "rgba(56,189,248,0.32)" } as React.CSSProperties}>
          <IconCheck className="stat-icon" />
          <div className="stat-label">Totalt behandlet</div>
          <div className="stat-value">{agent.totalProcessed}</div>
        </div>
      </div>

      {/* Last worked case */}
      <div className="panel panel-pad">
        <div className="stat-label">Siste sak agenten behandlet</div>
        {lastCase ? (
          <div className="row spread" style={{ marginTop: 12 }}>
            <div className="stack" style={{ gap: 6 }}>
              <Link href={`/cases/${lastCase.caseNumber}`} className="case-num" style={{ fontSize: 18 }}>
                {lastCase.caseNumber}
              </Link>
              <span>{lastCase.meta.customer || lastCase.meta.subject || "Ukjent"}</span>
              <span className="muted" style={{ fontSize: 12 }}>
                {lastCase.fileCount} {lastCase.fileCount === 1 ? "fil" : "filer"} · sist endret {formatRelative(lastCase.lastModified)}
              </span>
            </div>
            <Link href={`/cases/${lastCase.caseNumber}`} className="btn btn-primary">
              Åpne sak
            </Link>
          </div>
        ) : (
          <div className="muted" style={{ marginTop: 10 }}>Ingen kjøring registrert ennå.</div>
        )}
      </div>

      <p className="muted" style={{ fontSize: 12, marginTop: 16, maxWidth: 720 }}>
        Status avledes fra filenes endringstidspunkt i saksmappene. For eksakt
        styring kan agenten skrive en <code>agent-status.json</code> i
        Auto-XSALE-roten med feltene <code>state</code>, <code>lastRun</code>,{" "}
        <code>nextRun</code> og <code>intervalMinutes</code> — den overstyrer da
        de avledede verdiene.
      </p>
    </>
  );
}
