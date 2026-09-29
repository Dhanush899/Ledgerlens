import { useEffect, useState } from "react";
import { api, type Activity, type Answer, type MemoryInfo, type Vendor } from "../api";
import { Markdown, MemoryCard, Spinner } from "./ui";

const EXAMPLES = [
  "Which vendors bill freight separately, and what freight % have we accepted?",
  "Which vendors charge the wrong GST rate and how do we resolve it?",
  "Have we ever held or escalated an invoice? Why?",
  "Which vendors ship in partial lots?",
];

const OP_LABEL: Record<Activity["op"], string> = {
  retain: "RETAIN",
  recall: "RECALL",
  reflect: "REFLECT",
  reset: "RESET",
};

export default function MemoryConsole({ version }: { version: number }) {
  const [info, setInfo] = useState<MemoryInfo | null>(null);
  const [activity, setActivity] = useState<Activity[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [question, setQuestion] = useState("");
  const [scope, setScope] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.vendors().then(setVendors).catch(() => {});
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      Promise.all([api.memoryInfo(), api.activity()])
        .then(([i, a]) => {
          if (alive) {
            setInfo(i);
            setActivity(a);
          }
        })
        .catch(() => {});
    tick();
    const t = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [version]);

  const ask = async (q = question) => {
    if (q.trim().length < 3) return;
    setQuestion(q);
    setAsking(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await api.ask(q, scope || undefined));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setAsking(false);
    }
  };

  const cloud = info?.backend === "hindsight";

  return (
    <div className="console">
      <div className="card bank">
        <div className="bank-id">
          <div className={`bank-dot ${cloud ? "live" : ""}`} />
          <div>
            <div className="bank-title">{cloud ? "Hindsight Cloud" : "Local memory stand-in"}</div>
            <div className="muted small">
              bank <code>{info?.bank_id ?? "…"}</code>
              {info?.host && <> · <code>{info.host}</code></>}
              {info && !info.enabled && <b className="neg"> · recall OFF</b>}
            </div>
          </div>
        </div>
        <div className="bank-stats">
          {(["retain", "recall", "reflect"] as const).map((k) => (
            <div key={k}>
              <div className="kpi-value">{info?.counts[k] ?? 0}</div>
              <div className="muted small">{k} calls</div>
            </div>
          ))}
        </div>
        <p className="muted small bank-explain">
          <b>Retain</b> after every clerk decision · <b>Recall</b> the vendor's history before every suggestion ·{" "}
          <b>Reflect</b> to build vendor profiles and answer questions. Counters are for this server session.
        </p>
      </div>

      <div className="console-grid">
        <div className="card">
          <h3>Ask your AP memory</h3>
          <p className="muted small">Hindsight reflect reasons over every clerk decision it has retained.</p>
          <div className="ask-row">
            <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Scope">
              <option value="">All vendors</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>{v.name}</option>
              ))}
            </select>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ask()}
              placeholder="e.g. Which vendors bill freight separately?"
            />
            <button className="primary" onClick={() => ask()} disabled={asking || question.trim().length < 3}>
              {asking ? <Spinner /> : "Ask"}
            </button>
          </div>
          <div className="examples">
            {EXAMPLES.map((q) => (
              <button key={q} className="example" onClick={() => ask(q)} disabled={asking}>
                {q}
              </button>
            ))}
          </div>
          {error && <div className="banner error">{error}</div>}
          {asking && <p className="muted"><Spinner /> Reflecting over the memory bank…</p>}
          {answer && (
            <div className="answer">
              <Markdown text={answer.answer} />
              {answer.evidence.length > 0 && (
                <details>
                  <summary>Based on {answer.evidence.length} memories from {answer.backend === "hindsight" ? "Hindsight" : "the local store"}</summary>
                  <div className="memories">
                    {answer.evidence.map((m) => <MemoryCard key={m.id} m={m} />)}
                  </div>
                </details>
              )}
            </div>
          )}
        </div>

        <div className="card feed">
          <h3>Live memory activity</h3>
          {activity.length === 0 ? (
            <p className="muted small">No memory calls yet. Ask for a suggestion, decide an invoice or ask a question.</p>
          ) : (
            <ul>
              {activity.map((a) => (
                <li key={a.id} className={a.ok ? "" : "failed"}>
                  <span className={`op op-${a.op}`}>{OP_LABEL[a.op]}</span>
                  <div className="feed-body">
                    <div>{a.summary}</div>
                    <div className="muted small">
                      {a.at.slice(11)} · {a.ms >= 1000 ? `${(a.ms / 1000).toFixed(1)}s` : `${a.ms}ms`}
                      {a.result && a.op !== "retain" && <> · {a.result}</>}
                      {!a.ok && <> · failed</>}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
