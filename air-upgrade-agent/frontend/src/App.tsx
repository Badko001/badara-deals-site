import { useState } from "react";
import { DashboardPage } from "./pages/DashboardPage";
import { PriceWatchPage } from "./pages/PriceWatchPage";

type Tab = "upgrade" | "prices";

export function App() {
  const [tab, setTab] = useState<Tab>("upgrade");
  return (
    <>
      <nav className="tabs page" aria-label="Sections">
        <button className={`tab ${tab === "upgrade" ? "active" : ""}`} onClick={() => { setTab("upgrade"); }}>
          Surclassement
        </button>
        <button className={`tab ${tab === "prices" ? "active" : ""}`} onClick={() => { setTab("prices"); }}>
          Veille des prix
        </button>
      </nav>
      {tab === "upgrade" ? (
        <DashboardPage />
      ) : (
        <main className="page">
          <PriceWatchPage />
        </main>
      )}
    </>
  );
}
