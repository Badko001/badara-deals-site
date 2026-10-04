import { cabin, dateTime, euros, miles, unknown, yesNo } from "../services/format";
import type { CostLimits, FlightView, MonitoringState, UpgradeDecision } from "../types/api";
import { StatusBadge } from "./StatusBadge";

interface Props {
  flight: FlightView | null;
  decision: UpgradeDecision | null;
  limits: CostLimits;
  monitoring: MonitoringState;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function FlightCard({ flight, decision, limits, monitoring }: Props) {
  return (
    <section className="card">
      <header className="card-header">
        <h2>MY FLIGHT</h2>
        <StatusBadge status={monitoring.status} />
      </header>
      {flight === null ? (
        <p className="muted">Aucune observation pour l'instant. Lancez un contrôle.</p>
      ) : (
        <dl className="grid">
          <Row label="Flight" value={flight.flight_number ?? "Inconnu"} />
          <Row label="Réservation" value={flight.anonymized_booking_id ?? "—"} />
          <Row
            label="Trajet"
            value={`${flight.origin ?? "?"} → ${flight.destination ?? "?"}`}
          />
          <Row label="Départ" value={dateTime(flight.departure_datetime)} />
          <Row label="Passengers" value={String(limits.passengers_target)} />
          <Row label="Current Cabin" value={cabin(flight.current_cabin)} />
          <Row label="Target Cabin" value={cabin(flight.target_cabin)} />
          <Row label="Budget" value={euros(limits.cash_limit)} />
          <Row label="Miles" value={miles(limits.miles_limit)} />
          <Row label="Business Availability" value={yesNo(flight.business_available)} />
          <Row
            label="Sièges Business visibles"
            value={unknown(flight.business_seats_visible, (v) => `${v} (${flight.business_seats_provenance})`)}
          />
          <Row label="Upgrade Cost" value={euros(decision?.cash_cost)} />
          <Row label="Miles Cost" value={miles(decision?.miles_cost)} />
          <Row label="Check-in" value={flight.checkin_status ?? "Inconnu"} />
          <Row label="Confirmé par la compagnie" value={yesNo(flight.confirmed_by_airline)} />
          <Row label="Last Check" value={dateTime(monitoring.last_check)} />
        </dl>
      )}
      {flight !== null && (
        <ul className="passengers">
          {flight.passengers.map((p) => (
            <li key={p.anonymized_id}>
              <strong>{p.anonymized_id}</strong> · {cabin(p.current_cabin)} ·{" "}
              {p.eligibility ?? "éligibilité inconnue"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
