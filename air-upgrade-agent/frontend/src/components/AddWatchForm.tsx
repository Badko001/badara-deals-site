import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../services/api";
import type { FareCabin, NewPriceWatch } from "../types/api";

const isoIn = (days: number): string => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

const codes = (text: string): string[] =>
  text
    .split(/[\s,;]+/)
    .map((c) => c.trim().toUpperCase())
    .filter((c) => c.length > 0);

export function AddWatchForm({ onAdded }: { onAdded: () => void }) {
  const [name, setName] = useState("");
  const [origin, setOrigin] = useState("CDG");
  const [destinations, setDestinations] = useState("");
  const [from, setFrom] = useState(isoIn(7));
  const [to, setTo] = useState(isoIn(60));
  const [roundTrip, setRoundTrip] = useState(true);
  const [stay, setStay] = useState("7");
  const [pax, setPax] = useState("1");
  const [cabin, setCabin] = useState<FareCabin>("economy");
  const [maxPrice, setMaxPrice] = useState("");
  const [airlines, setAirlines] = useState("AF");
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const watch: NewPriceWatch = {
      name: name.trim() || `${origin.toUpperCase()} → ${destinations.toUpperCase()}`,
      origin: origin.trim().toUpperCase(),
      destinations: codes(destinations),
      depart_from: from,
      depart_to: to,
      trip_length_days: roundTrip ? Number(stay) : null,
      passengers: Number(pax),
      cabin,
      max_total_price: maxPrice.trim() ? Number(maxPrice) : null,
      airlines: codes(airlines),
    };
    try {
      await api.addWatch(watch);
      setError(null);
      setDestinations("");
      setName("");
      onAdded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  };

  return (
    <section className="card">
      <h2>Nouvelle veille</h2>
      <form className="watch-form" onSubmit={(e) => void submit(e)}>
        <label>
          Nom
          <input value={name} placeholder="Week-end au soleil" onChange={(e) => { setName(e.target.value); }} />
        </label>
        <label>
          Départ (code aéroport)
          <input value={origin} maxLength={3} onChange={(e) => { setOrigin(e.target.value); }} />
        </label>
        <label className="wide">
          Destinations (codes séparés par des virgules)
          <input
            value={destinations}
            placeholder="LIS, BCN, FCO"
            onChange={(e) => { setDestinations(e.target.value); }}
          />
        </label>
        <label>
          Partir entre le
          <input type="date" value={from} onChange={(e) => { setFrom(e.target.value); }} />
        </label>
        <label>
          et le
          <input type="date" value={to} onChange={(e) => { setTo(e.target.value); }} />
        </label>
        <label>
          Trajet
          <select value={roundTrip ? "rt" : "ow"} onChange={(e) => { setRoundTrip(e.target.value === "rt"); }}>
            <option value="rt">Aller-retour</option>
            <option value="ow">Aller simple</option>
          </select>
        </label>
        {roundTrip && (
          <label>
            Durée du séjour (jours)
            <input inputMode="numeric" value={stay} onChange={(e) => { setStay(e.target.value); }} />
          </label>
        )}
        <label>
          Passagers
          <select value={pax} onChange={(e) => { setPax(e.target.value); }}>
            {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <label>
          Cabine
          <select value={cabin} onChange={(e) => { setCabin(e.target.value as FareCabin); }}>
            <option value="economy">Economy</option>
            <option value="premium_economy">Premium</option>
            <option value="business">Business</option>
            <option value="first">First</option>
          </select>
        </label>
        <label>
          Prix max total (€, optionnel)
          <input inputMode="decimal" value={maxPrice} onChange={(e) => { setMaxPrice(e.target.value); }} />
        </label>
        <label>
          Compagnies (vide = toutes)
          <input value={airlines} placeholder="AF, KL, TO" onChange={(e) => { setAirlines(e.target.value); }} />
        </label>
        <button className="btn primary" type="submit">
          Ajouter
        </button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
