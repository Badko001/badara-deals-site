import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../services/api";
import type { BookingInfo, BookingSummary } from "../types/api";

interface Props {
  bookings: BookingSummary[];
  current: BookingInfo;
  isMock: boolean;
  onSelect: (bookingId: string) => void;
  onChanged: () => void;
}

const STATUS_ICON: Record<string, string> = {
  OPPORTUNITY_FOUND: "🟢",
  ACTION_REQUIRED: "🟠",
  MONITORING: "🔵",
  ERROR: "🔴",
};

const REFERENCE = /^[A-Za-z0-9]{5,8}$/;

export function BookingBar({ bookings, current, isMock, onSelect, onChanged }: Props) {
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [reference, setReference] = useState("");
  const [pax, setPax] = useState("1");
  const [newRef, setNewRef] = useState("");
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  };

  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (reference && !REFERENCE.test(reference.trim())) {
      setError("Référence : 5 à 8 lettres ou chiffres (ex. ABC123)");
      return;
    }
    await run(async () => {
      const created = await api.addBooking({
        label: label.trim() || "Nouvelle réservation",
        reference: reference.trim() || null,
        passengers_target: Number(pax),
        mock_scenario: null,
      });
      setAdding(false);
      setLabel("");
      setReference("");
      onSelect(created.booking_id);
      onChanged();
    });
  };

  const saveReference = async () => {
    if (!REFERENCE.test(newRef.trim())) {
      setError("Référence : 5 à 8 lettres ou chiffres (ex. ABC123)");
      return;
    }
    await run(async () => {
      await api.updateBooking(current.booking_id, { reference: newRef.trim() });
      setNewRef("");
      onChanged();
    });
  };

  const remove = async () => {
    if (!window.confirm(`Supprimer la réservation « ${current.label} » de la surveillance ?`)) return;
    await run(async () => {
      await api.deleteBooking(current.booking_id);
      const next = bookings.find((b) => b.booking.booking_id !== current.booking_id);
      if (next) onSelect(next.booking.booking_id);
      onChanged();
    });
  };

  return (
    <section className="card booking-bar">
      <div className="booking-row">
        <label className="booking-select">
          Réservation surveillée
          <select value={current.booking_id} onChange={(e) => { onSelect(e.target.value); }}>
            {bookings.map(({ booking, status, has_pending_confirmation }) => (
              <option key={booking.booking_id} value={booking.booking_id}>
                {STATUS_ICON[status] ?? "⚪"} {booking.label}
                {booking.reference_redacted ? ` (${booking.reference_redacted})` : ""} ·{" "}
                {booking.passengers_target} pass.
                {has_pending_confirmation ? " · confirmation en attente" : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="actions">
          <button className="btn" onClick={() => { setAdding(!adding); }}>
            {adding ? "Annuler" : "+ Ajouter une réservation"}
          </button>
          {bookings.length > 1 && (
            <button className="btn" onClick={() => void remove()}>
              Supprimer
            </button>
          )}
        </div>
      </div>

      {!isMock && current.reference_redacted && !current.reference_in_memory && (
        <div className="booking-row small">
          <span className="muted">
            Référence {current.reference_redacted} : ressaisissez-la (elle n'est jamais enregistrée en clair)
            pour que l'agent ouvre cette réservation.
          </span>
          <input
            value={newRef}
            maxLength={8}
            placeholder="Référence complète"
            onChange={(e) => { setNewRef(e.target.value.toUpperCase()); }}
          />
          <button className="btn" onClick={() => void saveReference()}>
            Valider
          </button>
        </div>
      )}

      {adding && (
        <form className="watch-form" onSubmit={(e) => void add(e)}>
          <label>
            Nom (pour vous repérer)
            <input value={label} placeholder="Vacances Noël" maxLength={80} onChange={(e) => { setLabel(e.target.value); }} />
          </label>
          <label>
            Référence de réservation
            <input
              value={reference}
              placeholder="ABC123 (facultatif)"
              maxLength={8}
              onChange={(e) => { setReference(e.target.value.toUpperCase()); }}
            />
          </label>
          <label>
            Passagers à surclasser
            <select value={pax} onChange={(e) => { setPax(e.target.value); }}>
              {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button className="btn primary" type="submit">
            Ajouter
          </button>
          <p className="small muted wide">
            La référence sert uniquement à ouvrir la bonne réservation sur le site Air France. Elle reste en
            mémoire ; seule sa version masquée (PNR_****123) est enregistrée.
          </p>
        </form>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
