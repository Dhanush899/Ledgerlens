import type { ReactNode } from "react";
import type { Action, Memory } from "../api";

export const FLAG_LABELS: Record<string, string> = {
  DUPLICATE: "Duplicate",
  MISSING_PO: "No PO",
  PRICE_VARIANCE: "Price variance",
  QTY_MISMATCH: "Qty mismatch",
  TAX_MISMATCH: "GST mismatch",
  UNEXPECTED_LINE: "Unexpected line",
  TOTAL_MISMATCH: "Total mismatch",
};

export function FlagChip({ code, severity }: { code: string; severity?: string }) {
  return <span className={`chip flag sev-${severity ?? "medium"}`}>{FLAG_LABELS[code] ?? code}</span>;
}

const ACTION_LABEL: Record<Action, string> = { approve: "Approve", hold: "Hold", escalate: "Escalate" };

export function ActionPill({ action, subtle }: { action: Action; subtle?: boolean }) {
  return <span className={`pill act-${action}${subtle ? " subtle" : ""}`}>{ACTION_LABEL[action]}</span>;
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="conf" title={`${pct}% confidence`}>
      <div className="conf-track">
        <div className="conf-fill" style={{ width: `${pct}%` }} />
      </div>
      <span>{pct}%</span>
    </div>
  );
}

export function MemoryCard({ m, cited, index }: { m: Memory; cited?: boolean; index?: number }) {
  const tags = m.tags.filter((t) => !t.startsWith("vendor:"));
  return (
    <div className={`memory${cited ? " cited" : ""}`}>
      <div className="memory-head">
        {index !== undefined && <span className="mem-label">M{index}</span>}
        {cited && <span className="mem-cited">cited</span>}
        {m.timestamp && <span className="muted small">{m.timestamp.slice(0, 10)}</span>}
        <span className="mem-tags">
          {tags.map((t) => (
            <span key={t} className="tag">
              {t.replace("flag:", "").replace("decision:", "→ ")}
            </span>
          ))}
        </span>
      </div>
      <p>{m.text}</p>
    </div>
  );
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

/** Tiny, safe markdown renderer for reflect output (headings, bullets, bold, italics). */
export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) {
      blocks.push(
        <ul key={`ul${blocks.length}`}>
          {list.map((l, i) => (
            <li key={i}>{inline(l)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)$/);
    if (bullet) {
      list.push(bullet[1]);
      continue;
    }
    flush();
    const h = line.match(/^#{1,6}\s+(.*)$/);
    if (h) blocks.push(<h4 key={blocks.length}>{inline(h[1])}</h4>);
    else if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  return <div className="md">{blocks}</div>;
}

function inline(s: string): (string | ReactNode)[] {
  return s.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) return <em key={i}>{part.slice(1, -1)}</em>;
    return part;
  });
}
