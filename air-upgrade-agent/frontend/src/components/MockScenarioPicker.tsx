import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { MockScenarios } from "../types/api";

export function MockScenarioPicker({ onChange }: { onChange: () => void }) {
  const [data, setData] = useState<MockScenarios | null>(null);

  useEffect(() => {
    api.mockScenarios().then(setData, () => {
      setData(null);
    });
  }, []);

  if (data === null) return null;

  const select = async (name: string) => {
    await api.setMockScenario(name);
    setData({ ...data, current: name });
    await api.checkNow();
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
        <a href="/api/mock/page" target="_blank" rel="noreferrer">
          Voir la page simulée
        </a>
      </p>
    </section>
  );
}
