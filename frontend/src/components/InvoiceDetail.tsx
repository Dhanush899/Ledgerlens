import { useEffect, useState } from "react";
import { api, fmtINR, type Action, type Compare, type InvoiceContext, type Suggestion } from "../api";
import { toast } from "../toast";
import { ActionPill, ConfidenceBar, FlagChip, MemoryCard, Spinner } from "./ui";

const GUARDRAIL_TEXT: Record<string, string> = {
  "duplicate-never-approved": "Guardrail: suspected duplicates are never auto-approved",
  "approve-requires-precedent": "Guardrail: approval needs a precedent in memory",
  "safe-fallback": "Safe fallback: agent unavailable, escalated",
  "straight-through": "Straight-through: no exceptions",
};

export default function InvoiceDetail({ id, memoryOn, onChanged }: { id: string; memoryOn: boolean; onChanged: () => void }) {
  const [ctx, setCtx] = useState<InvoiceContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState<Action | null>(null);
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [comparing, setComparing] = useState(false);

  const load = () => api.invoice(id).then(setCtx).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [id]);

  if (!ctx) return <div className="empty">{error ?? <Spinner />}</div>;
  const { invoice, vendor, po, grns, flags, suggestion, decision } = ctx;

  const ask = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.suggest(id);
      await load();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const decide = async (action: Action) => {
    setSaving(action);
    try {
      const d = await api.decide(id, action, note);
      if (d.retained_memory) {
        const where = d.memory_backend === "hindsight" ? "Hindsight Cloud" : "local memory";
        const secs = d.retain_ms != null ? ` in ${(d.retain_ms / 1000).toFixed(1)}s` : "";
        toast("memory", `Saved to ${where}${secs}`,
          `LedgerLens will remember this for ${ctx.vendor.name}'s next invoice.`);
      }
      await load();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(null);
    }
  };

  const compare = async () => {
    setComparing(true);
    setError(null);
    try {
      setCmp(await api.compare(id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setComparing(false);
    }
  };

  const poLines = new Map(po?.lines.map((l) => [l.sku, l]) ?? []);
  const received = new Map<string, number>();
  grns.forEach((g) => g.lines.forEach((l) => received.set(l.sku, (received.get(l.sku) ?? 0) + l.qty_received)));
  const flaggedSkus = new Set(flags.map((f) => f.details.sku as string | undefined).filter(Boolean));
  const citedIds = new Set(suggestion?.cited_memories.map((m) => m.id));

  return (
    <div className="invoice">
      <div className="inv-header">
        <div>
          <h2>{vendor.name}</h2>
          <div className="muted small">
            GSTIN {vendor.gstin} · {vendor.city} · {vendor.payment_terms} · {vendor.category}
          </div>
        </div>
        <div className="inv-meta">
          <div className="big">{fmtINR(invoice.total)}</div>
          <div className="muted small">
            {invoice.invoice_number} · {invoice.date} · {invoice.tax_type}
          </div>
          <div className="muted small">
            {po ? <>PO {po.po_number}</> : <b className="neg">No PO</b>}
            {grns.map((g) => <span key={g.grn_number}> · {g.grn_number}</span>)}
          </div>
        </div>
      </div>

      <div className="table-scroll">
      <table className="match">
        <thead>
          <tr>
            <th>Item</th>
            <th className="num">PO qty × rate</th>
            <th className="num">Received</th>
            <th className="num">Invoiced qty × rate</th>
            <th className="num">GST PO → Inv</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {invoice.lines.map((l) => {
            const p = poLines.get(l.sku);
            const rec = received.get(l.sku);
            const bad = flaggedSkus.has(l.sku) || !p;
            return (
              <tr key={l.sku} className={bad ? "bad" : ""}>
                <td>
                  <div>{l.description}</div>
                  <div className="muted small">{l.sku}</div>
                </td>
                <td className="num">{p ? `${p.qty} × ${fmtINR(p.unit_price)}` : "not on PO"}</td>
                <td className={`num ${p && rec !== undefined && rec < l.qty ? "neg" : ""}`}>{p ? rec ?? 0 : "–"}</td>
                <td className={`num ${p && p.unit_price !== l.unit_price ? "neg" : ""}`}>
                  {l.qty} × {fmtINR(l.unit_price)}
                </td>
                <td className={`num ${p && p.gst_rate !== l.gst_rate ? "neg" : ""}`}>
                  {p ? `${p.gst_rate}% → ${l.gst_rate}%` : `${l.gst_rate}%`}
                </td>
                <td className="num">{fmtINR(l.qty * l.unit_price)}</td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr><td colSpan={5}>Subtotal</td><td className="num">{fmtINR(invoice.subtotal)}</td></tr>
          <tr><td colSpan={5}>GST</td><td className="num">{fmtINR(invoice.tax)}</td></tr>
          <tr className="total"><td colSpan={5}>Invoice total (as stated)</td><td className="num">{fmtINR(invoice.total)}</td></tr>
        </tfoot>
      </table>
      </div>

      <div className="section">
        <h3>Three-way match exceptions</h3>
        {flags.length === 0 ? (
          <p className="ok">✓ PO, goods receipt and invoice agree. Eligible for straight-through approval.</p>
        ) : (
          <ul className="flags">
            {flags.map((f, i) => (
              <li key={i}>
                <FlagChip code={f.code} severity={f.severity} />
                <span>{f.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="section suggestion-section">
        <div className="section-head">
          <h3>LedgerLens suggestion</h3>
          <div className="head-buttons">
            {flags.length > 0 && (
              <button onClick={compare} disabled={comparing || loading} title="Run the agent with and without memory side by side">
                {comparing ? <><Spinner /> Comparing…</> : "Compare with memory OFF"}
              </button>
            )}
            <button className="primary" onClick={ask} disabled={loading}>
              {loading ? <><Spinner /> Recalling memory & reasoning…</> : suggestion ? "Ask again" : "Ask LedgerLens"}
            </button>
          </div>
        </div>
        {error && <div className="banner error">{error}</div>}
        {cmp && (
          <div className="compare">
            <CompareCol title="Without memory" s={cmp.without_memory} />
            <CompareCol title={`With Hindsight memory (${cmp.recalled.length} recalled)`} s={cmp.with_memory} highlight />
            <button className="ghost small close-cmp" onClick={() => setCmp(null)} aria-label="Close comparison">✕</button>
          </div>
        )}
        {suggestion ? (
          <div className={`suggestion act-border-${suggestion.action}`}>
            <div className="sugg-top">
              <ActionPill action={suggestion.action} />
              <ConfidenceBar value={suggestion.confidence} />
              {suggestion.needs_human ? <span className="chip human">Needs a human</span>
                : <span className="chip auto">Auto-handled</span>}
              <span className="muted small right">
                {suggestion.memory_enabled ? `${suggestion.recalled_count} memories recalled` : "memory off"}
                {suggestion.model && ` · ${suggestion.model}`} · {suggestion.latency_ms} ms
              </span>
            </div>
            <p className="reason">{suggestion.reason}</p>
            {suggestion.guardrail && <div className="guardrail">{GUARDRAIL_TEXT[suggestion.guardrail] ?? suggestion.guardrail}</div>}
            {suggestion.recalled.length > 0 && (
              <details open={suggestion.cited_memories.length > 0}>
                <summary>
                  Memory evidence: {suggestion.cited_memories.length} cited of {suggestion.recalled.length} recalled
                </summary>
                <div className="memories">
                  {[...suggestion.recalled]
                    .sort((a, b) => Number(citedIds.has(b.id)) - Number(citedIds.has(a.id)))
                    .map((m) => (
                      <MemoryCard key={m.id} m={m} cited={citedIds.has(m.id)}
                                  index={suggestion.recalled.findIndex((x) => x.id === m.id) + 1} />
                    ))}
                </div>
              </details>
            )}
            {suggestion.memory_enabled && suggestion.recalled.length === 0 && flags.length > 0 && (
              <p className="muted small">No past decisions for this vendor yet: first time the agent sees this pattern.</p>
            )}
          </div>
        ) : (
          <p className="muted">
            Ask the agent: it recalls this vendor's history from {memoryOn ? "memory" : "(memory is OFF)"} and proposes approve / hold / escalate.
          </p>
        )}
      </div>

      <div className="section">
        <h3>Clerk decision</h3>
        {decision ? (
          <div className="decision">
            <div>
              <ActionPill action={decision.action} /> by <b>{decision.decided_by}</b>
              {decision.suggested_action && (
                <span className={`chip ${decision.agreed ? "auto" : "human"}`}>
                  {decision.agreed ? "matched suggestion" : `overrode ${decision.suggested_action}`}
                </span>
              )}
            </div>
            {decision.note && <p className="note">“{decision.note}”</p>}
            {decision.retained_memory && (
              <div className="retained">
                <b>Retained to memory</b>
                <p>{decision.retained_memory}</p>
              </div>
            )}
          </div>
        ) : (
          <>
            <textarea
              placeholder="Why? This note is retained to memory and teaches the agent (e.g. 'Freight under 2% is agreed in contract').."
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
            />
            <div className="decide-buttons">
              {(["approve", "hold", "escalate"] as Action[]).map((a) => (
                <button key={a} className={`act-btn act-${a}${suggestion?.action === a ? " suggested" : ""}`}
                        onClick={() => decide(a)} disabled={!!saving}>
                  {saving === a ? <Spinner /> : null}
                  {saving === a && flags.length > 0 ? "Saving to memory…" : null}
                  {saving !== a && a[0].toUpperCase() + a.slice(1)}
                  {saving !== a && suggestion?.action === a && <span className="small"> (suggested)</span>}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function CompareCol({ title, s, highlight }: { title: string; s: Suggestion; highlight?: boolean }) {
  return (
    <div className={`compare-col${highlight ? " hl" : ""}`}>
      <div className="muted small">{title}</div>
      <div className="sugg-top">
        <ActionPill action={s.action} />
        <ConfidenceBar value={s.confidence} />
      </div>
      <p className="small">{s.reason}</p>
      {s.cited_memories.length > 0 && (
        <div className="muted small">cites: {s.cited_memories.map((m) => `“${m.text.slice(0, 70)}…”`).join(" · ")}</div>
      )}
    </div>
  );
}
