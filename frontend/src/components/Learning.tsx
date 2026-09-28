import { useEffect, useRef, useState } from "react";
import { api, type Metrics, type ReplayStatus, type WeekMetric } from "../api";
import { Spinner } from "./ui";

export default function Learning({ version, onChanged }: { version: number; onChanged: () => void }) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [status, setStatus] = useState<ReplayStatus | null>(null);
  const [day, setDay] = useState(30);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const refresh = async () => {
    const [m, s] = await Promise.all([api.metrics(), api.replayStatus()]);
    setMetrics(m);
    setStatus(s);
    return s;
  };

  const poll = () => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      const s = await refresh();
      if (!s.running && timer.current) {
        window.clearInterval(timer.current);
        timer.current = null;
        onChanged();
      }
    }, 1500);
  };

  useEffect(() => {
    refresh().then((s) => s.running && poll());
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [version]);

  const run = async (label: string, fn: () => Promise<unknown>, then?: string) => {
    setBusy(label);
    setMsg(null);
    try {
      const r = await fn();
      if (then) setMsg(then.replace("{n}", String((r as { retained?: number }).retained ?? "")));
      await refresh();
      onChanged();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const startReplay = async () => {
    setMsg(null);
    setStatus(await api.replay(day));
    poll();
  };

  const t = metrics?.totals;
  const humanPct = t && t.exceptions ? Math.round((100 * t.human_needed) / t.exceptions) : null;

  return (
    <div className="learning">
      <div className="controls card">
        <div>
          <h3>Replay September</h3>
          <p className="muted small">
            Processes every undecided invoice up to the chosen day: the agent suggests, a simulated clerk decides (ground truth),
            and each decision is retained to memory. Watch the share of exceptions needing a human drop.
          </p>
        </div>
        <div className="control-row">
          <label>
            through day <b>{day}</b>
            <input type="range" min={1} max={30} value={day} onChange={(e) => setDay(Number(e.target.value))} />
          </label>
          <button className="primary" onClick={startReplay} disabled={!!status?.running || !!busy}>
            {status?.running ? <><Spinner /> Replaying {status.done}/{status.total}</> : "Replay month"}
          </button>
          <button onClick={() => run("seed", api.seed, "Retained {n} August decisions into memory.")} disabled={!!busy || !!status?.running}>
            {busy === "seed" ? <Spinner /> : null} Seed August history
          </button>
          <button className="danger" disabled={!!busy || !!status?.running}
                  onClick={() => confirm("Wipe memory and all decisions?") && run("reset", () => api.reset(true, true), "Memory and queue reset.")}>
            Reset all
          </button>
          <button className="ghost" disabled={!!busy || !!status?.running}
                  onClick={() => run("resetq", () => api.reset(false, true), "Queue reset (memory kept).")}>
            Reset queue only
          </button>
        </div>
        {status?.running && (
          <div className="progress">
            <div style={{ width: `${status.total ? (100 * status.done) / status.total : 0}%` }} />
          </div>
        )}
        {status?.error && <div className="banner error">Replay stopped: {status.error}</div>}
        {msg && <div className="banner info">{msg}</div>}
      </div>

      <div className="kpis">
        <Kpi label="Invoices processed" value={t ? `${t.processed}/${t.invoices}` : "–"} />
        <Kpi label="Exceptions" value={t ? String(t.exceptions) : "–"} />
        <Kpi label="Needed a human" value={humanPct === null ? "–" : `${humanPct}%`} />
        <Kpi label="Agent agreed with clerk" value={t?.agreement == null ? "–" : `${Math.round(t.agreement * 100)}%`} />
      </div>

      <div className="card">
        <h3>Human-needed exceptions by week</h3>
        {metrics && metrics.weeks.some((w) => w.exceptions) ? <Chart weeks={metrics.weeks} /> : (
          <p className="muted">No decisions yet. Run a replay (optionally after seeding August history).</p>
        )}
        <div className="legend">
          <span><i className="sw human" /> needed a human (escalated or &lt;70% confidence)</span>
          <span><i className="sw auto" /> handled by the agent</span>
          <span><i className="sw line" /> % needing a human</span>
        </div>
      </div>

      <div className="card">
        <h3>Weekly detail</h3>
        <table className="match">
          <thead>
            <tr><th>Week</th><th className="num">Processed</th><th className="num">Clean (STP)</th><th className="num">Exceptions</th>
              <th className="num">Human</th><th className="num">Agent</th><th className="num">Agreement</th></tr>
          </thead>
          <tbody>
            {metrics?.weeks.map((w) => (
              <tr key={w.label}>
                <td>{w.label}</td><td className="num">{w.processed}</td><td className="num">{w.clean}</td>
                <td className="num">{w.exceptions}</td><td className="num">{w.human_needed}</td>
                <td className="num">{w.auto_handled}</td>
                <td className="num">{w.agreement == null ? "–" : `${Math.round(w.agreement * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="kpi card">
      <div className="kpi-value">{value}</div>
      <div className="muted small">{label}</div>
    </div>
  );
}

function Chart({ weeks }: { weeks: WeekMetric[] }) {
  const W = 640, H = 260, pad = { l: 40, r: 44, t: 16, b: 36 };
  const max = Math.max(4, ...weeks.map((w) => w.exceptions));
  const band = (W - pad.l - pad.r) / weeks.length;
  const bw = Math.min(64, band * 0.5);
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const yr = (r: number) => pad.t + (H - pad.t - pad.b) * (1 - r);
  const cx = (i: number) => pad.l + band * i + band / 2;
  const pts = weeks.map((w, i) => (w.human_rate == null ? null : [cx(i), yr(w.human_rate)] as const))
    .filter((p): p is readonly [number, number] => p !== null);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Weekly human-needed exceptions">
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line x1={pad.l} x2={W - pad.r} y1={yr(f)} y2={yr(f)} className="grid" />
          <text x={pad.l - 8} y={yr(f) + 4} className="axis" textAnchor="end">{Math.round(max * f)}</text>
          <text x={W - pad.r + 8} y={yr(f) + 4} className="axis">{Math.round(f * 100)}%</text>
        </g>
      ))}
      {weeks.map((w, i) => (
        <g key={w.label}>
          <rect x={cx(i) - bw / 2} y={y(w.human_needed)} width={bw} height={y(0) - y(w.human_needed)} className="bar-human" rx="3" />
          <rect x={cx(i) - bw / 2} y={y(w.exceptions)} width={bw} height={y(w.human_needed) - y(w.exceptions)} className="bar-auto" rx="3" />
          <text x={cx(i)} y={H - 14} className="axis" textAnchor="middle">{w.label.split(" (")[0]}</text>
          {w.exceptions > 0 && (
            <text x={cx(i)} y={y(w.exceptions) - 6} className="axis strong" textAnchor="middle">{w.exceptions}</text>
          )}
        </g>
      ))}
      {pts.length > 1 && <polyline points={pts.map((p) => p.join(",")).join(" ")} className="rate-line" />}
      {pts.map(([px, py], i) => <circle key={i} cx={px} cy={py} r="4.5" className="rate-dot" />)}
    </svg>
  );
}
