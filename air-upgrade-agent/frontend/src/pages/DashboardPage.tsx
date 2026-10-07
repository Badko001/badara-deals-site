import { useEffect, useState } from "react";
import { BookingBar } from "../components/BookingBar";
import { DecisionPanel } from "../components/DecisionPanel";
import { FlightCard } from "../components/FlightCard";
import { LimitsForm } from "../components/LimitsForm";
import { MockScenarioPicker } from "../components/MockScenarioPicker";
import { NotificationsList } from "../components/NotificationsList";
import { OpportunityPanel } from "../components/OpportunityPanel";
import { BOOKING_NOT_FOUND, useDashboard } from "../hooks/useDashboard";
import { api } from "../services/api";

const STORAGE_KEY = "aua.selectedBooking";

function loadSelected(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function saveSelected(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, id);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable: selection simply not remembered */
  }
}

export function DashboardPage() {
  const [selected, setSelected] = useState<string | null>(loadSelected);
  const { data, error, refresh } = useDashboard(selected);
  const [actionError, setActionError] = useState<string | null>(null);

  const select = (id: string | null) => {
    saveSelected(id);
    setSelected(id);
    setActionError(null);
  };

  useEffect(() => {
    // The remembered booking was deleted: fall back to the first one.
    if (error === BOOKING_NOT_FOUND && selected !== null) select(null);
  }, [error, selected]);

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
  const bookingId = data.booking.booking_id;
  const execution = data.last_execution;
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

      <BookingBar
        bookings={data.bookings}
        current={data.booking}
        isMock={isMock}
        onSelect={select}
        onChanged={() => void refresh()}
      />

      <div className="toolbar">
        {!isMock && !config.session_ready && (
          <button className="btn" onClick={() => void act(api.startSession)}>
            Ouvrir le navigateur (connexion manuelle)
          </button>
        )}
        <button className="btn" onClick={() => void act(() => api.checkNow(bookingId))}>
          Vérifier maintenant
        </button>
        {monitoring.running ? (
          <button className="btn" onClick={() => void act(() => api.stopMonitoring(bookingId))}>
            Arrêter la surveillance
          </button>
        ) : (
          <button className="btn primary" onClick={() => void act(() => api.startMonitoring(bookingId))}>
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
          onDone={() => {
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
          {isMock && (
            <MockScenarioPicker key={bookingId} bookingId={bookingId} onChange={() => void refresh()} />
          )}
          <LimitsForm
            key={`${bookingId}-${data.limits.passengers_target}`}
            bookingId={bookingId}
            limits={data.limits}
            onSaved={() => void refresh()}
          />
          <NotificationsList items={data.notifications} />
        </div>
      </div>
    </main>
  );
}
