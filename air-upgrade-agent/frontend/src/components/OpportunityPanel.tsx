import { useState } from "react";
import { api } from "../services/api";
import { cabin, dateTime, euros, miles } from "../services/format";
import type { PendingConfirmation, UpgradeExecutionResult } from "../types/api";

interface Props {
  pending: PendingConfirmation;
  dryRun: boolean;
  onDone: (result: UpgradeExecutionResult | null) => void;
}

export function OpportunityPanel({ pending, dryRun, onDone }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { summary } = pending;

  const run = async (action: "confirm" | "decline") => {
    setBusy(true);
    setError(null);
    try {
      if (action === "confirm") {
        onDone(await api.confirm(pending.confirmation_id));
      } else {
        await api.decline(pending.confirmation_id);
        onDone(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card opportunity" aria-live="assertive">
      <h2>OPPORTUNITÉ DÉTECTÉE</h2>
      <p className="big">
        {pending.passengers} passagers · {cabin(summary.from_cabin)} → {cabin(summary.to_cabin)}
      </p>
      <dl className="grid">
        <div className="row">
          <dt>Coût</dt>
          <dd>{euros(pending.max_cash)}</dd>
        </div>
        <div className="row">
          <dt>Miles</dt>
          <dd>{miles(pending.max_miles)}</dd>
        </div>
        <div className="row">
          <dt>Vol</dt>
          <dd>{summary.flight ?? "?"}</dd>
        </div>
        <div className="row">
          <dt>Départ → Destination</dt>
          <dd>
            {summary.origin ?? "?"} → {summary.destination ?? "?"}
          </dd>
        </div>
        <div className="row">
          <dt>Expire</dt>
          <dd>{dateTime(pending.expires_at)}</dd>
        </div>
      </dl>
      <p className="muted small">
        L'agent relira la page officielle avant d'agir. Seule la compagnie peut confirmer le
        changement de cabine.{" "}
        {dryRun && <strong>DRY_RUN actif : aucune modification réelle ne sera effectuée.</strong>}
      </p>
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="btn primary" disabled={busy} onClick={() => void run("confirm")}>
          CONFIRMER
        </button>
        <button className="btn" disabled={busy} onClick={() => void run("decline")}>
          REFUSER
        </button>
      </div>
    </section>
  );
}
