import { useCallback, useEffect, useState } from "react";
import { api, type Health } from "./api";
import { onToast, toast, type Toast } from "./toast";
import Queue from "./components/Queue";
import Vendors from "./components/Vendors";
import Learning from "./components/Learning";
import MemoryConsole from "./components/MemoryConsole";

export type Tab = "queue" | "vendors" | "memory" | "learning";

const TAB_LABEL: Record<Tab, string> = {
  queue: "Invoice queue",
  vendors: "Vendor memory",
  memory: "Hindsight",
  learning: "Learning curve",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("queue");
  const [focus, setFocus] = useState<{ id: string; n: number } | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
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
    toast("info", r.enabled ? "Memory ON" : "Memory OFF",
      r.enabled ? "The agent recalls each vendor's history from Hindsight again."
        : "The agent now gets no recalled history: watch it behave like a generic rules bot.");
  };

  const openInvoice = (id: string) => {
    setTab("queue");
    setFocus((f) => ({ id, n: (f?.n ?? 0) + 1 }));
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
          {(Object.keys(TAB_LABEL) as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {TAB_LABEL[t]}
            </button>
          ))}
        </nav>
        <div className="top-right">
          <button className="ghost guide-btn" onClick={() => setGuideOpen((o) => !o)}>Demo guide</button>
          {health && (
            <>
              <button className={`backend ${health.memory_backend}`} onClick={() => setTab("memory")}
                      title={`bank ${health.bank_id}${health.memory_host ? " @ " + health.memory_host : ""}`}>
                {health.memory_backend === "hindsight" ? "● Hindsight Cloud" : "Local memory"}
              </button>
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
      {guideOpen && (
        <DemoGuide
          onClose={() => setGuideOpen(false)}
          openInvoice={openInvoice}
          goto={setTab}
          onChanged={refresh}
          memoryOn={health?.memory_enabled ?? true}
          toggleMemory={toggleMemory}
        />
      )}
      <main>
        {tab === "queue" && <Queue version={version} memoryOn={health?.memory_enabled ?? true} focus={focus} />}
        {tab === "vendors" && <Vendors version={version} />}
        {tab === "memory" && <MemoryConsole version={version} />}
        {tab === "learning" && <Learning version={version} onChanged={refresh} />}
      </main>
      <Toasts />
    </div>
  );
}

// Invoice ids come from the deterministic dataset (scripts/generate_data.py, seed 42).
const FIRST_QUIRK = "INV-0001"; // Deccan Steel: freight 1.45% on first invoice
const REPEAT_QUIRK = "INV-0017"; // Deccan Steel again: freight ~1.4%
const DUPLICATE = "INV-0053"; // Lakshmi Hardware re-sends LHM/…/0099 as …-A
const FREIGHT_SPIKE = "INV-0058"; // Coromandel: freight 9.6% vs ~1.5% history

function DemoGuide(props: {
  onClose: () => void;
  openInvoice: (id: string) => void;
  goto: (t: Tab) => void;
  onChanged: () => void;
  memoryOn: boolean;
  toggleMemory: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (key: string, fn: () => Promise<unknown>, done: string) => {
    setBusy(key);
    try {
      await fn();
      toast("info", done);
      props.onChanged();
    } catch (e) {
      toast("error", "Failed", (e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const steps: { title: string; text: string; button: string; run: () => void; key: string }[] = [
    {
      key: "reset", title: "Start with an empty memory",
      text: "Wipes the Hindsight bank and the queue so the agent knows nothing.",
      button: "Reset everything",
      run: () => confirm("Wipe the Hindsight bank and all decisions?") &&
        act("reset", () => api.reset(true, true), "Memory bank and queue wiped"),
    },
    {
      key: "first", title: "First quirky invoice → escalated",
      text: "Deccan Steel adds 1.45% freight. Ask LedgerLens: with no precedent it escalates. Approve with a note like “Freight under 2% is agreed in contract”. That note is retained to Hindsight.",
      button: "Open invoice", run: () => props.openInvoice(FIRST_QUIRK),
    },
    {
      key: "repeat", title: "Same quirk next time → approved, citing memory",
      text: "Deccan Steel's next invoice: the agent recalls your decision and approves, highlighting the memory it used. Click “Compare with memory OFF” for the before/after.",
      button: "Open invoice", run: () => props.openInvoice(REPEAT_QUIRK),
    },
    {
      key: "replay", title: "Replay the month",
      text: "A simulated clerk works through September up to day 22. Every decision is retained, and human-needed exceptions drop week by week.",
      button: "Replay to day 22",
      run: () => act("replay", async () => { await api.replay(22); props.goto("learning"); }, "Replay started"),
    },
    {
      key: "dup", title: "Duplicate with altered number → held",
      text: "Lakshmi Hardware re-sends an invoice as “…-A”. Its rounding quirk is known, but the duplicate is never approved.",
      button: "Open invoice", run: () => props.openInvoice(DUPLICATE),
    },
    {
      key: "spike", title: "Freight spike beyond the learned pattern → held",
      text: "Coromandel bills 9.6% freight; memory says ~1.5% is normal, so the agent holds it.",
      button: "Open invoice", run: () => props.openInvoice(FREIGHT_SPIKE),
    },
    {
      key: "reflect", title: "Ask the memory",
      text: "Hindsight reflect answers questions across every decision and builds vendor profiles.",
      button: "Open Hindsight console", run: () => props.goto("memory"),
    },
    {
      key: "off", title: "Toggle memory off",
      text: "Turn memory off and ask again on any quirky invoice: it goes back to escalating everything.",
      button: props.memoryOn ? "Turn memory OFF" : "Turn memory ON", run: props.toggleMemory,
    },
  ];

  return (
    <div className="guide card">
      <div className="section-head">
        <h3>Demo guide: watch the agent get smarter</h3>
        <button className="ghost" onClick={props.onClose} aria-label="Close guide">✕</button>
      </div>
      <ol>
        {steps.map((s) => (
          <li key={s.key}>
            <div>
              <b>{s.title}</b>
              <div className="muted small">{s.text}</div>
            </div>
            <button onClick={s.run} disabled={!!busy}>{busy === s.key ? <Spinner /> : s.button}</button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Spinner() {
  return <span className="spinner" />;
}

function Toasts() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(
    () =>
      onToast((t) => {
        setItems((xs) => [...xs, t]);
        window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), t.kind === "memory" ? 7000 : 4000);
      }),
    [],
  );
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          <b>{t.title}</b>
          {t.body && <div className="small">{t.body}</div>}
        </div>
      ))}
    </div>
  );
}
