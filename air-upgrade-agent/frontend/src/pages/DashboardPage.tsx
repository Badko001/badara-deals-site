import { useState } from "react";
import { DecisionPanel } from "../components/DecisionPanel";
import { FlightCard } from "../components/FlightCard";
import { LimitsForm } from "../components/LimitsForm";
import { MockScenarioPicker } from "../components/MockScenarioPicker";
import { NotificationsList } from "../components/NotificationsList";
import { OpportunityPanel } from "../components/OpportunityPanel";
import { useDashboard } from "../hooks/useDashboard";
import { api } from "../services/api";
import type { UpgradeExecutionResult } from "../types/api";

export function DashboardPage() {
  const { data, error, refresh } = useDashboard();
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<UpgradeExecutionResult | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      setActionError(null);
      await fn();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Erreur");
    }
    await refresh();
  };

  if (data === null) {
    return <main className="page">{error ? <p className="error">{error}</p> : <p>Chargement…</p>}</main>;
  }

  const { config, monitoring } = data;
  const execution = lastResult ?? data.last_execution;
  const isMock = config.mock_scenario !== null;

  return (
    <main className="page">
      <header className="top">
        <div>
          <h1>Air Upgrade Agent</h1>
          <p className="muted small">
            Economy → Business · {data.limits.passengers_target} passagers ensemble · surveillance
            de vos offres officielles uniquement
          </p>
        </div>
        <div className="flags">
          {config.dry_run && <span className="flag warn">DRY_RUN</span>}
          {isMock && <span className="flag">MOCK</span>}
          <span className="flag">{config.llm_enabled ? "LLM Azure" : "Moteur déterministe"}</span>
        </div>
      </header>

      {error && <p className="error">{error}</p>}
      {actionError && <p className="error">{actionError}</p>}

      <div className="toolbar">
        {!isMock && !config.session_ready && (
          <button className="btn" onClick={() => void act(api.startSession)}>
            Ouvrir le navigateur (connexion manuelle)
          </button>
        )}
        <button className="btn" onClick={() => void act(api.checkNow)}>
          Vérifier maintenant
        </button>
        {monitoring.running ? (
          <button className="btn" onClick={() => void act(api.stopMonitoring)}>
            Arrêter la surveillance
          </button>
        ) : (
          <button className="btn primary" onClick={() => void act(api.startMonitoring)}>
            Démarrer la surveillance
          </button>
        )}
      </div>

      {execution && (
        <section className={`card result result-${execution.status.toLowerCase()}`}>
          <h2>{execution.status}</h2>
          <p>{execution.message}</p>
        </section>
      )}

      {data.pending_confirmation && (
        <OpportunityPanel
          pending={data.pending_confirmation}
          dryRun={config.dry_run}
          onDone={(result) => {
            setLastResult(result);
            void refresh();
          }}
        />
      )}

      <div className="columns">
        <div>
          <FlightCard
            flight={data.flight}
            decision={data.decision}
            limits={data.limits}
            monitoring={monitoring}
          />
          <DecisionPanel decision={data.decision} />
        </div>
        <div>
          {isMock && <MockScenarioPicker onChange={() => void refresh()} />}
          <LimitsForm limits={data.limits} onSaved={() => void refresh()} />
          <NotificationsList items={data.notifications} />
        </div>
      </div>
    </main>
  );
}
