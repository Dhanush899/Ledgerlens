export type Action = "approve" | "hold" | "escalate";

export interface Flag {
  code: string;
  severity: "low" | "medium" | "high";
  message: string;
  details: Record<string, unknown>;
}

export interface Line {
  sku: string;
  description: string;
  qty: number;
  unit_price: number;
  gst_rate: number;
}

export interface Invoice {
  id: string;
  invoice_number: string;
  vendor_id: string;
  po_number: string | null;
  date: string;
  day: number;
  due_in: string;
  tax_type: string;
  lines: Line[];
  subtotal: number;
  tax: number;
  total: number;
}

export interface Vendor {
  id: string;
  name: string;
  gstin: string;
  state_code: string;
  city: string;
  payment_terms: string;
  category: string;
  invoices?: number;
  decided?: number;
}

export interface Memory {
  id: string;
  text: string;
  tags: string[];
  timestamp: string | null;
  score: number | null;
}

export interface Suggestion {
  action: Action;
  confidence: number;
  reason: string;
  cited_memories: Memory[];
  recalled: Memory[];
  recalled_count: number;
  memory_enabled: boolean;
  model: string | null;
  guardrail: string | null;
  latency_ms: number;
  needs_human: boolean;
}

export interface Decision {
  action: Action;
  note: string;
  decided_by: string;
  decided_at: string;
  had_exceptions: boolean;
  suggested_action: Action | null;
  agreed: boolean;
  needs_human: boolean;
  retained_memory: string | null;
  retain_ms: number | null;
  memory_backend: string;
}

export interface InvoiceContext {
  invoice: Invoice;
  vendor: Vendor;
  po: { po_number: string; date: string; lines: Line[] } | null;
  grns: { grn_number: string; date: string; lines: { sku: string; qty_received: number }[] }[];
  flags: Flag[];
  suggestion: Suggestion | null;
  decision: Decision | null;
}

export interface QueueRow {
  id: string;
  invoice_number: string;
  day: number;
  date: string;
  vendor_id: string;
  vendor_name: string;
  total: number;
  flags: string[];
  max_severity: string | null;
  suggestion: { action: Action; confidence: number; needs_human: boolean } | null;
  decision: { action: Action; decided_by: string } | null;
}

export interface Health {
  memory_backend: string;
  memory_enabled: boolean;
  bank_id: string;
  memory_host: string | null;
  llm_configured: boolean;
  models: string[];
}

export interface WeekMetric {
  label: string;
  processed: number;
  clean: number;
  exceptions: number;
  human_needed: number;
  auto_handled: number;
  human_rate: number | null;
  agreement: number | null;
}

export interface Metrics {
  weeks: WeekMetric[];
  totals: { invoices: number; processed: number; exceptions: number; human_needed: number; agreement: number | null };
}

export interface ReplayStatus {
  running: boolean;
  done: number;
  total: number;
  current: string | null;
  error: string | null;
  through_day: number | null;
}

export interface MemoryInfo {
  backend: string;
  bank_id: string;
  host: string | null;
  enabled: boolean;
  counts: { retain: number; recall: number; reflect: number };
}

export interface Activity {
  id: number;
  op: "retain" | "recall" | "reflect" | "reset";
  summary: string;
  vendor_id: string | null;
  ok: boolean;
  at: string;
  ms: number;
  result: string | null;
}

export interface Compare {
  with_memory: Suggestion;
  without_memory: Suggestion;
  recalled: Memory[];
}

export interface Answer {
  answer: string;
  evidence: Memory[];
  backend: string;
}

async function req<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not json */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<Health>("/health"),
  invoices: () => req<QueueRow[]>("/invoices"),
  invoice: (id: string) => req<InvoiceContext>(`/invoices/${id}`),
  suggest: (id: string) => req<Suggestion>(`/invoices/${id}/suggest`, {}),
  decide: (id: string, action: Action, note: string) => req<Decision>(`/invoices/${id}/decision`, { action, note }),
  vendors: () => req<Vendor[]>("/vendors"),
  vendorMemories: (id: string) => req<Memory[]>(`/vendors/${id}/memories`),
  vendorProfile: (id: string) => req<{ profile: string; evidence: Memory[]; backend: string }>(`/vendors/${id}/profile`),
  compare: (id: string) => req<Compare>(`/invoices/${id}/compare`, {}),
  memoryInfo: () => req<MemoryInfo>("/memory"),
  activity: () => req<Activity[]>("/memory/activity"),
  ask: (question: string, vendor_id?: string) => req<Answer>("/memory/ask", { question, vendor_id: vendor_id || null }),
  toggleMemory: (enabled: boolean) => req<{ enabled: boolean }>("/memory/toggle", { enabled }),
  seed: () => req<{ retained: number }>("/memory/seed", {}),
  reset: (memory = true, queue = true) => req<{ ok: boolean }>("/reset", { memory, queue }),
  replay: (through_day: number) => req<ReplayStatus>("/replay", { through_day }),
  replayStatus: () => req<ReplayStatus>("/replay"),
  metrics: () => req<Metrics>("/metrics"),
};

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
export const fmtINR = (n: number) => inr.format(n);
export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
