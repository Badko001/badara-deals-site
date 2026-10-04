import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../services/api";
import type { CostLimits } from "../types/api";

export function LimitsForm({ limits, onSaved }: { limits: CostLimits; onSaved: () => void }) {
  const [cash, setCash] = useState(String(limits.cash_limit));
  const [mi, setMi] = useState(String(limits.miles_limit));
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const cashValue = Number(cash);
    const milesValue = Number(mi);
    if (!(cashValue >= 0) || !Number.isInteger(milesValue) || milesValue < 0) {
      setError("Valeurs invalides");
      return;
    }
    try {
      await api.setLimits(cashValue, milesValue);
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
        {free ? "Mode FREE UPGRADE : 0 € et 0 Miles." : "Attention : mode avec budget."}
      </p>
      <form className="limits" onSubmit={(e) => void submit(e)}>
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
