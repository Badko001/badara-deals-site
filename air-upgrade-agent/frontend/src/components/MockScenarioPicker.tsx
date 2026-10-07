import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { MockScenarios } from "../types/api";

export function MockScenarioPicker({
  bookingId,
  onChange,
}: {
  bookingId: string | null;
  onChange: () => void;
}) {
  const [data, setData] = useState<MockScenarios | null>(null);

  useEffect(() => {
    api.mockScenarios(bookingId).then(setData, () => {
      setData(null);
    });
  }, [bookingId]);

  if (data === null) return null;

  const select = async (name: string) => {
    await api.setMockScenario(bookingId, name);
    setData({ ...data, current: name });
    await api.checkNow(bookingId);
    onChange();
  };

  return (
    <section className="card mock">
      <h2>MOCK AIR FRANCE</h2>
      <p className="small muted">Simulation locale, données fictives. Le site réel n'est jamais contacté.</p>
      <select value={data.current} onChange={(e) => void select(e.target.value)}>
        {Object.entries(data.scenarios).map(([name, description]) => (
          <option key={name} value={name}>
            {name} — {description}
          </option>
        ))}
      </select>
      <p className="small">
        <a href={api.mockPageUrl(bookingId)} target="_blank" rel="noreferrer">
          Voir la page simulée
        </a>
      </p>
    </section>
  );
}
