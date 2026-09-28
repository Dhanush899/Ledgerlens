import { useCallback, useEffect, useState } from "react";
import { api, type Health } from "./api";
import Queue from "./components/Queue";
import Vendors from "./components/Vendors";
import Learning from "./components/Learning";

type Tab = "queue" | "vendors" | "learning";

export default function App() {
  const [tab, setTab] = useState<Tab>("queue");
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  // bumps whenever memory/queue state changes globally so views refetch
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((v) => v + 1), []);

  useEffect(() => {
    api.health().then(setHealth).catch((e) => setError(String(e.message ?? e)));
  }, [version]);

  const toggleMemory = async () => {
    if (!health) return;
    const r = await api.toggleMemory(!health.memory_enabled);
    setHealth({ ...health, memory_enabled: r.enabled });
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="8" fill="var(--brand)" />
            <circle cx="14" cy="14" r="7" fill="none" stroke="white" strokeWidth="3" />
            <path d="M19 19l6 6" stroke="white" strokeWidth="3" strokeLinecap="round" />
          </svg>
          <div>
            <div className="brand-name">LedgerLens</div>
            <div className="brand-sub">AP exception agent that learns from every clerk decision</div>
          </div>
        </div>
        <nav className="tabs">
          {(["queue", "vendors", "learning"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {{ queue: "Invoice queue", vendors: "Vendor memory", learning: "Learning curve" }[t]}
            </button>
          ))}
        </nav>
        <div className="top-right">
          {health && (
            <>
              <span className={`backend ${health.memory_backend}`} title={`bank: ${health.bank_id}`}>
                {health.memory_backend === "hindsight" ? "Hindsight" : "Local memory"}
              </span>
              {!health.llm_configured && <span className="backend warn">No GROQ_API_KEY</span>}
              <button
                className={`mem-toggle ${health.memory_enabled ? "on" : "off"}`}
                onClick={toggleMemory}
                title="Before/after demo: with memory off the agent gets no recalled history"
              >
                <span className="knob" />
                MEMORY {health.memory_enabled ? "ON" : "OFF"}
              </button>
            </>
          )}
        </div>
      </header>
      {error && <div className="banner error">Backend unreachable: {error}. Start it with <code>uvicorn app.api:app</code>.</div>}
      {health && !health.memory_enabled && (
        <div className="banner off">Memory is OFF: the agent sees no past decisions and behaves like a generic rules bot.</div>
      )}
      <main>
        {tab === "queue" && <Queue version={version} memoryOn={health?.memory_enabled ?? true} />}
        {tab === "vendors" && <Vendors version={version} />}
        {tab === "learning" && <Learning version={version} onChanged={refresh} />}
      </main>
    </div>
  );
}
