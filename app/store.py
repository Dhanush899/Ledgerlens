"""Loads the synthetic dataset and keeps queue state (suggestions, decisions) on disk."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .rules import match_invoice


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Store:
    """In-process view of vendors, POs, GRNs, invoices and the clerk's work so far."""

    def __init__(self, data_dir: Path, state_path: Path):
        self.state_path = state_path
        self.vendors: dict[str, dict] = {v["id"]: v for v in _load(data_dir / "vendors.json")}
        self.pos: dict[str, dict] = {p["po_number"]: p for p in _load(data_dir / "purchase_orders.json")}
        self.grns_by_po: dict[str, list[dict]] = defaultdict(list)
        for g in _load(data_dir / "goods_receipts.json"):
            self.grns_by_po[g["po_number"]].append(g)
        self.invoices: list[dict] = sorted(_load(data_dir / "invoices.json"), key=lambda i: (i["day"], i["id"]))
        self.by_id: dict[str, dict] = {i["id"]: i for i in self.invoices}
        self.history: list[dict] = _load(data_dir / "history.json")
        truth = _load(data_dir / "ground_truth.json")
        self.vendor_quirks: dict[str, list[str]] = truth.pop("_vendor_quirks", {})
        self.ground_truth: dict[str, dict] = truth
        self._flags: dict[str, list[dict]] = {}
        self.state: dict[str, dict] = {"decisions": {}, "suggestions": {}}
        if state_path.exists():
            self.state.update(_load(state_path))

    # ---- documents -------------------------------------------------------------
    def flags_for(self, invoice_id: str) -> list[dict]:
        """Three-way match flags (cached). Duplicates are checked against earlier invoices."""
        if invoice_id not in self._flags:
            inv = self.by_id[invoice_id]
            idx = self.invoices.index(inv)
            po = self.pos.get(inv["po_number"]) if inv.get("po_number") else None
            grns = self.grns_by_po.get(inv["po_number"], []) if po else []
            flags = match_invoice(inv, po, grns, prior_invoices=self.invoices[:idx])
            self._flags[invoice_id] = [f.to_dict() for f in flags]
        return self._flags[invoice_id]

    def context(self, invoice_id: str) -> dict[str, Any]:
        """Invoice with its vendor, PO, GRNs, flags and queue state."""
        inv = self.by_id[invoice_id]
        po = self.pos.get(inv["po_number"]) if inv.get("po_number") else None
        return {
            "invoice": inv,
            "vendor": self.vendors[inv["vendor_id"]],
            "po": po,
            "grns": self.grns_by_po.get(inv["po_number"], []) if po else [],
            "flags": self.flags_for(invoice_id),
            "suggestion": self.state["suggestions"].get(invoice_id),
            "decision": self.state["decisions"].get(invoice_id),
        }

    # ---- queue state -----------------------------------------------------------
    def record_suggestion(self, invoice_id: str, suggestion: dict) -> None:
        self.state["suggestions"][invoice_id] = suggestion
        self.save()

    def record_decision(self, invoice_id: str, decision: dict) -> None:
        self.state["decisions"][invoice_id] = decision
        self.save()

    def reset(self) -> None:
        """Forget all suggestions and decisions (memory is reset separately)."""
        self.state = {"decisions": {}, "suggestions": {}}
        self.save()

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
