import { useCallback, useEffect, useState } from "react";
import { AddWatchForm } from "../components/AddWatchForm";
import { api } from "../services/api";
import { dateTime } from "../services/format";
import type { FareQuote, PriceAlert, PriceWatchStatus, WatchSummary } from "../types/api";

const REFRESH_MS = 10000;

const shortDate = (iso: string): string =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });

function QuoteLine({ quote }: { quote: FareQuote | null }) {
  if (quote === null) return <span className="muted">Pas encore de prix</span>;
  const perPax = Math.round(quote.total_price / quote.passengers);
  return (
    <span>
      <strong>
        {Math.round(quote.total_price).toLocaleString("fr-FR")} {quote.currency}
      </strong>{" "}
      → {quote.destination} · {shortDate(quote.depart_date)}
      {quote.return_date ? ` → ${shortDate(quote.return_date)}` : ""} · {perPax} €/pers. ·{" "}
      {quote.carrier ?? "?"}
    </span>
  );
}

export function PriceWatchPage() {
  const [watches, setWatches] = useState<WatchSummary[]>([]);
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [status, setStatus] = useState<PriceWatchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [w, a, s] = await Promise.all([api.watches(), api.priceAlerts(), api.priceWatchStatus()]);
      setWatches(w);
      setAlerts(a);
      setStatus(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backend injoignable");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [refresh]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(null);
      await refresh();
    }
  };

  return (
    <>
      <section className="card">
        <header className="card-header">
          <h2>Veille des prix</h2>
          {status && (
            <span className={`badge ${status.running ? "badge-monitoring" : "badge-idle"}`}>
              {status.running ? "EN VEILLE" : "ARRÊTÉE"}
            </span>
          )}
        </header>
        <p className="small muted">
          Prix publiés uniquement ({status?.source === "mock" ? "SIMULATION — prix fictifs" : `source : ${status?.source ?? "?"}`}).
          Vérification toutes les {status ? Math.round(status.interval_seconds / 3600) : "?"} h au plus souvent.
          Pas de réservation ici : vous réservez et payez sur le site officiel de la compagnie.
          {status?.last_run ? ` Dernière vérification : ${dateTime(status.last_run)}.` : ""}
        </p>
        <div className="toolbar">
          {status?.running ? (
            <button className="btn" onClick={() => void act("loop", api.stopPriceWatch)}>
              Arrêter la veille
            </button>
          ) : (
            <button className="btn primary" onClick={() => void act("loop", api.startPriceWatch)}>
              Démarrer la veille automatique
            </button>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </section>

      <div className="columns">
        <div>
          {watches.map(({ watch, best_current, lowest_ever, last_check, quotes_count }) => (
            <section key={watch.watch_id} className="card">
              <header className="card-header">
                <h2>{watch.name}</h2>
                <span className="small muted">
                  {watch.passengers} passager{watch.passengers > 1 ? "s" : ""} ·{" "}
                  {watch.trip_length_days ? `A/R ${watch.trip_length_days} j` : "aller simple"}
                </span>
              </header>
              <p className="small muted">
                {watch.origin} → {watch.destinations.join(", ")} · départ entre le{" "}
                {shortDate(watch.depart_from)} et le {shortDate(watch.depart_to)}
                {watch.max_total_price !== null ? ` · alerte sous ${watch.max_total_price} €` : ""}
                {watch.airlines.length ? ` · ${watch.airlines.join(", ")}` : " · toutes compagnies"}
              </p>
              <dl className="grid single">
                <div className="row">
                  <dt>Meilleur prix actuel</dt>
                  <dd>
                    <QuoteLine quote={best_current} />
                  </dd>
                </div>
                <div className="row">
                  <dt>Plus bas observé</dt>
                  <dd>
                    <QuoteLine quote={lowest_ever} />
                  </dd>
                </div>
              </dl>
              <p className="small muted">
                {quotes_count} prix relevé(s) · dernière vérification {dateTime(last_check)}
              </p>
              <div className="actions">
                <button
                  className="btn"
                  disabled={busy !== null}
                  onClick={() => void act(watch.watch_id, () => api.checkWatch(watch.watch_id))}
                >
                  {busy === watch.watch_id ? "Vérification…" : "Vérifier maintenant"}
                </button>
                <button
                  className="btn"
                  disabled={busy !== null}
                  onClick={() => {
                    if (window.confirm(`Supprimer la veille « ${watch.name} » ?`)) {
                      void act(`del-${watch.watch_id}`, () => api.deleteWatch(watch.watch_id));
                    }
                  }}
                >
                  Supprimer
                </button>
              </div>
            </section>
          ))}
          <AddWatchForm onAdded={() => void refresh()} />
        </div>
        <div>
          <section className="card">
            <h2>Alertes prix</h2>
            {alerts.length === 0 ? (
              <p className="muted">Aucune alerte pour l'instant.</p>
            ) : (
              <ul className="list">
                {alerts.map((a) => (
                  <li key={`${a.watch_id}-${a.timestamp}`}>
                    <span className="small muted">{dateTime(a.timestamp)}</span> <code>{a.kind}</code>
                    <div className="pre">{a.message}</div>
                    {a.booking_url && (
                      <a className="btn primary small-btn" href={a.booking_url} target="_blank" rel="noreferrer">
                        Réserver sur le site officiel
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
