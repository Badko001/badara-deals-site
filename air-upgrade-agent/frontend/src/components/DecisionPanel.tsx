import { euros, miles } from "../services/format";
import type { UpgradeDecision } from "../types/api";

export function DecisionPanel({ decision }: { decision: UpgradeDecision | null }) {
  if (decision === null) return null;
  return (
    <section className="card">
      <header className="card-header">
        <h2>Recommendation</h2>
        <span className={`pill pill-${decision.status.toLowerCase()}`}>{decision.status}</span>
      </header>
      <p className="big">{decision.recommendation}</p>
      <p className="muted">{decision.reason}</p>
      <p className="small muted">
        Confiance {Math.round(decision.confidence * 100)} % · décidé par {decision.decided_by} ·
        sièges observés {decision.business_seats_observed ?? "inconnu"} /{" "}
        {decision.business_seats_required} requis · passagers éligibles{" "}
        {decision.passengers_eligible ?? "inconnu"} / {decision.passengers_target}
      </p>
      {decision.rejected_options.length > 0 && (
        <>
          <h3>Offres observées non retenues</h3>
          <ul className="list">
            {decision.rejected_options.map((o) => (
              <li key={o.option_id}>
                <code>{o.option_id}</code> — {euros(o.cash_cost)} / {miles(o.miles_cost)} —{" "}
                {o.reason}
              </li>
            ))}
          </ul>
        </>
      )}
      {decision.data_issues.length > 0 && (
        <>
          <h3>Qualité des données</h3>
          <ul className="list small">
            {decision.data_issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
