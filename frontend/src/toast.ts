export type ToastKind = "memory" | "info" | "error";
export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  body?: string;
}

type Listener = (t: Toast) => void;
const listeners = new Set<Listener>();
let seq = 0;

/** Show a transient notification (rendered by <Toasts/> in App). */
export function toast(kind: ToastKind, title: string, body?: string) {
  const t = { id: ++seq, kind, title, body };
  listeners.forEach((l) => l(t));
}

export function onToast(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
