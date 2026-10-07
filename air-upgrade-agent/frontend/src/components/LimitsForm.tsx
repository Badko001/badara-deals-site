import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../services/api";
import type { CostLimits } from "../types/api";

export function LimitsForm({ limits, onSaved }: { limits: CostLimits; onSaved: () => void }) {
  const [cash, setCash] = useState(String(limits.cash_limit));
  const [mi, setMi] = useState(String(limits.miles_limit));
  const [pax, setPax] = useState(String(limits.passengers_target));
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const cashValue = Number(cash);
    const milesValue = Number(mi);
    const paxValue = Number(pax);
    if (
      !(cashValue >= 0) ||
      !Number.isInteger(milesValue) ||
      milesValue < 0 ||
      !Number.isInteger(paxValue) ||
      paxValue < 1 ||
      paxValue > 9
    ) {
      setError("Valeurs invalides (passagers : 1 à 9)");
      return;
    }
    try {
      await api.setLimits(cashValue, milesValue, paxValue);
      setError(null);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  };

  const free = limits.cash_limit === 0 && limits.miles_limit === 0;
  return (
    <section className="card">
      <h2>Limites</h2>
      <p className="small muted">
        {free ? "Mode FREE UPGRADE : 0 € et 0 Miles." : "Attention : mode avec budget."}{" "}
        Tous les passagers doivent être surclassés ensemble.
      </p>
      <form className="limits" onSubmit={(e) => void submit(e)}>
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
          Cash max (€)
          <input inputMode="decimal" value={cash} onChange={(e) => { setCash(e.target.value); }} />
        </label>
        <label>
          Miles max
          <input inputMode="numeric" value={mi} onChange={(e) => { setMi(e.target.value); }} />
        </label>
        <button className="btn" type="submit">
          Enregistrer
        </button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}
