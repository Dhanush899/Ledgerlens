import { useEffect, useMemo, useState } from "react";
import { api, fmtDate, fmtINR, type QueueRow } from "../api";
import { ActionPill, FlagChip } from "./ui";
import InvoiceDetail from "./InvoiceDetail";

type Filter = "pending" | "exceptions" | "decided" | "all";

export default function Queue({ version, memoryOn, focus }: {
  version: number;
  memoryOn: boolean;
  focus: { id: string; n: number } | null;
}) {
  const [rows, setRows] = useState<QueueRow[]>([]);
  const [filter, setFilter] = useState<Filter>("pending");
  const [selected, setSelected] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    api.invoices().then(setRows).catch(() => setRows([]));
  }, [version, tick]);

  const visible = useMemo(() => {
    return rows.filter((r) => {
      if (filter === "pending") return !r.decision;
      if (filter === "exceptions") return r.flags.length > 0;
      if (filter === "decided") return !!r.decision;
      return true;
    });
  }, [rows, filter]);

  // Jump to an invoice requested elsewhere (demo guide).
  useEffect(() => {
    if (focus) {
      setFilter("all");
      setSelected(focus.id);
      window.setTimeout(() => document.getElementById(`row-${focus.id}`)?.scrollIntoView({ block: "center" }), 50);
    }
  }, [focus]);

  useEffect(() => {
    if (!selected && visible.length) setSelected(visible.find((r) => r.flags.length)?.id ?? visible[0].id);
  }, [visible, selected]);

  const counts = {
    pending: rows.filter((r) => !r.decision).length,
    exceptions: rows.filter((r) => r.flags.length).length,
    decided: rows.filter((r) => r.decision).length,
    all: rows.length,
  };

  return (
    <div className="queue-layout">
      <aside className="queue">
        <div className="filters">
          {(Object.keys(counts) as Filter[]).map((f) => (
            <button key={f} className={filter === f ? "active" : ""} onClick={() => setFilter(f)}>
              {f} <span className="count">{counts[f]}</span>
            </button>
          ))}
        </div>
        <ul className="rows">
          {visible.map((r) => (
            <li key={r.id} id={`row-${r.id}`} className={`${selected === r.id ? "selected" : ""} ${r.decision ? "done" : ""}`}
                onClick={() => setSelected(r.id)}>
              <div className="row-top">
                <span className="vendor">{r.vendor_name}</span>
                <span className="amount">{fmtINR(r.total)}</span>
              </div>
              <div className="row-mid muted small">
                <span>{r.invoice_number}</span>
                <span>{fmtDate(r.date)}</span>
              </div>
              <div className="row-bottom">
                <span className="chips">
                  {r.flags.length === 0 ? <span className="chip clean">Clean match</span>
                    : r.flags.map((f) => <FlagChip key={f} code={f} severity={f === "DUPLICATE" ? "high" : undefined} />)}
                </span>
                {r.decision ? <ActionPill action={r.decision.action} />
                  : r.suggestion ? <ActionPill action={r.suggestion.action} subtle /> : null}
              </div>
            </li>
          ))}
          {visible.length === 0 && <li className="empty">Nothing here.</li>}
        </ul>
      </aside>
      <section className="detail">
        {selected ? (
          <InvoiceDetail key={`${selected}-${version}`} id={selected} memoryOn={memoryOn}
                         onChanged={() => setTick((t) => t + 1)} />
        ) : (
          <div className="empty">Select an invoice</div>
        )}
      </section>
    </div>
  );
}
