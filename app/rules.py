"""Deterministic three-way match: invoice vs purchase order vs goods receipts.

The rules never "learn" anything. They only describe *what* is off about an
invoice. Deciding whether that is acceptable for a given vendor is the agent's
job, informed by memory.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

Invoice = dict[str, Any]
PurchaseOrder = dict[str, Any]
GoodsReceipt = dict[str, Any]

# Flag codes
DUPLICATE = "DUPLICATE"
MISSING_PO = "MISSING_PO"
PRICE_VARIANCE = "PRICE_VARIANCE"
QTY_MISMATCH = "QTY_MISMATCH"
TAX_MISMATCH = "TAX_MISMATCH"
UNEXPECTED_LINE = "UNEXPECTED_LINE"
TOTAL_MISMATCH = "TOTAL_MISMATCH"


@dataclass(frozen=True)
class Tolerances:
    """Thresholds for the deterministic match."""

    price_pct: float = 0.5          # unit price variance allowed vs PO, in %
    total_abs: float = 0.01         # stated vs computed total, in INR
    dup_amount_abs: float = 1.0     # duplicate if totals within this many INR
    dup_number_similarity: float = 0.85


@dataclass
class Flag:
    """One exception raised by the three-way match."""

    code: str
    severity: str  # "low" | "medium" | "high"
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


def compute_totals(invoice: Invoice) -> dict[str, float]:
    """Recompute subtotal, tax and total from the invoice's own lines."""
    subtotal = 0.0
    tax = 0.0
    for line in invoice["lines"]:
        amount = line["qty"] * line["unit_price"]
        subtotal += amount
        tax += amount * line["gst_rate"] / 100
    subtotal = round(subtotal, 2)
    tax = round(tax, 2)
    return {"subtotal": subtotal, "tax": tax, "total": round(subtotal + tax, 2)}


def normalise_invoice_number(number: str) -> str:
    """Uppercase and strip everything except letters and digits."""
    return re.sub(r"[^A-Z0-9]", "", number.upper())


def invoice_numbers_similar(a: str, b: str, threshold: float = 0.85) -> bool:
    """Fuzzy match two vendor invoice numbers (e.g. 'LHM/0412' vs 'LHM/0412-A').

    A suffix/prefix added to the same number is a match. Otherwise the numbers
    must be textually similar *and* carry the same digits, so consecutive
    invoices of a fixed-fee vendor (…/0130 vs …/0131) are not duplicates.
    """
    na, nb = normalise_invoice_number(a), normalise_invoice_number(b)
    if not na or not nb:
        return False
    if na == nb or na.startswith(nb) or nb.startswith(na):
        return True
    if re.sub(r"\D", "", na) != re.sub(r"\D", "", nb):
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def find_duplicates(
    invoice: Invoice, prior_invoices: list[Invoice], tol: Tolerances = Tolerances()
) -> list[Invoice]:
    """Return earlier invoices from the same vendor that look like this one."""
    matches = []
    for prior in prior_invoices:
        if prior["id"] == invoice["id"] or prior["vendor_id"] != invoice["vendor_id"]:
            continue
        if abs(prior["total"] - invoice["total"]) > tol.dup_amount_abs:
            continue
        if invoice_numbers_similar(
            prior["invoice_number"], invoice["invoice_number"], tol.dup_number_similarity
        ):
            matches.append(prior)
    return matches


def _received_qty(sku: str, grns: list[GoodsReceipt]) -> float:
    return sum(l["qty_received"] for g in grns for l in g["lines"] if l["sku"] == sku)


def match_invoice(
    invoice: Invoice,
    po: PurchaseOrder | None,
    grns: list[GoodsReceipt],
    prior_invoices: list[Invoice] | None = None,
    tol: Tolerances = Tolerances(),
) -> list[Flag]:
    """Run the three-way match and return every exception found.

    An empty list means the invoice is clean and can be approved straight through.
    """
    flags: list[Flag] = []

    for dup in find_duplicates(invoice, prior_invoices or [], tol):
        flags.append(Flag(
            DUPLICATE, "high",
            f"Looks like a duplicate of {dup['invoice_number']} ({dup['id']}): "
            f"same vendor, total within INR {tol.dup_amount_abs:.0f}, similar number.",
            {"duplicate_of": dup["id"], "duplicate_number": dup["invoice_number"],
             "amount": invoice["total"], "original_amount": dup["total"]},
        ))

    if po is None:
        flags.append(Flag(
            MISSING_PO, "medium",
            "Invoice does not reference a valid purchase order."
            if not invoice.get("po_number") else
            f"Purchase order {invoice['po_number']} not found.",
            {"po_number": invoice.get("po_number"), "amount": invoice["total"]},
        ))
    else:
        flags.extend(_line_checks(invoice, po, grns, tol))

    computed = compute_totals(invoice)
    diff = round(invoice["total"] - computed["total"], 2)
    if abs(diff) > tol.total_abs:
        flags.append(Flag(
            TOTAL_MISMATCH, "low" if abs(diff) <= 1 else "high",
            f"Stated total INR {invoice['total']:,.2f} differs from line sum "
            f"INR {computed['total']:,.2f} by INR {diff:+,.2f}.",
            {"stated_total": invoice["total"], "computed_total": computed["total"], "difference": diff},
        ))
    return flags


def _line_checks(
    invoice: Invoice, po: PurchaseOrder, grns: list[GoodsReceipt], tol: Tolerances
) -> list[Flag]:
    flags: list[Flag] = []
    po_lines = {l["sku"]: l for l in po["lines"]}
    goods_subtotal = sum(
        l["qty"] * l["unit_price"] for l in invoice["lines"] if l["sku"] in po_lines
    )

    for line in invoice["lines"]:
        sku = line["sku"]
        po_line = po_lines.get(sku)
        amount = round(line["qty"] * line["unit_price"], 2)

        if po_line is None:
            pct = round(100 * amount / goods_subtotal, 2) if goods_subtotal else None
            flags.append(Flag(
                UNEXPECTED_LINE, "medium",
                f"Line '{line['description']}' (INR {amount:,.2f}"
                + (f", {pct}% of goods value" if pct is not None else "")
                + ") is not on the PO.",
                {"sku": sku, "description": line["description"], "amount": amount,
                 "pct_of_goods": pct},
            ))
            continue

        variance_pct = round(100 * (line["unit_price"] - po_line["unit_price"]) / po_line["unit_price"], 2)
        if abs(variance_pct) > tol.price_pct:
            flags.append(Flag(
                PRICE_VARIANCE, "medium" if abs(variance_pct) <= 5 else "high",
                f"{line['description']}: unit price INR {line['unit_price']:,.2f} vs PO "
                f"INR {po_line['unit_price']:,.2f} ({variance_pct:+.2f}%).",
                {"sku": sku, "po_price": po_line["unit_price"], "invoice_price": line["unit_price"],
                 "variance_pct": variance_pct,
                 "variance_amount": round((line["unit_price"] - po_line["unit_price"]) * line["qty"], 2)},
            ))

        if line["gst_rate"] != po_line["gst_rate"]:
            flags.append(Flag(
                TAX_MISMATCH, "medium",
                f"{line['description']}: GST charged {line['gst_rate']}% but PO says "
                f"{po_line['gst_rate']}%.",
                {"sku": sku, "po_gst_rate": po_line["gst_rate"], "invoice_gst_rate": line["gst_rate"],
                 "excess_tax": round(amount * (line["gst_rate"] - po_line["gst_rate"]) / 100, 2)},
            ))

        received = _received_qty(sku, grns)
        if line["qty"] > received or line["qty"] > po_line["qty"]:
            received_pct = round(100 * received / line["qty"], 1) if line["qty"] else 0.0
            reasons = []
            if line["qty"] > received:
                reasons.append(f"only {received:g} received ({received_pct}%)")
            if line["qty"] > po_line["qty"]:
                reasons.append(f"PO quantity is {po_line['qty']:g}")
            flags.append(Flag(
                QTY_MISMATCH, "medium",
                f"{line['description']}: invoiced {line['qty']:g} but " + " and ".join(reasons) + ".",
                {"sku": sku, "invoiced_qty": line["qty"], "received_qty": received,
                 "po_qty": po_line["qty"], "received_pct": received_pct},
            ))
    return flags
