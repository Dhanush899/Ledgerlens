"""Tests for the deterministic three-way match."""
from __future__ import annotations

import copy

import pytest

from app.rules import (DUPLICATE, MISSING_PO, PRICE_VARIANCE, QTY_MISMATCH, TAX_MISMATCH,
                       TOTAL_MISMATCH, UNEXPECTED_LINE, compute_totals, invoice_numbers_similar,
                       match_invoice)


def make_po():
    return {"po_number": "PO-1", "vendor_id": "V01", "date": "2026-09-01", "lines": [
        {"sku": "A", "description": "Item A", "qty": 100, "unit_price": 50.0, "gst_rate": 18},
        {"sku": "B", "description": "Item B", "qty": 10, "unit_price": 1000.0, "gst_rate": 12},
    ]}


def make_grns(qa=100, qb=10):
    return [{"grn_number": "GRN-1", "po_number": "PO-1", "date": "2026-09-05",
             "lines": [{"sku": "A", "qty_received": qa}, {"sku": "B", "qty_received": qb}]}]


def make_invoice(**overrides):
    inv = {"id": "INV-1", "invoice_number": "DST/26-27/0100", "vendor_id": "V01", "po_number": "PO-1",
           "date": "2026-09-10", "lines": copy.deepcopy(make_po()["lines"])}
    inv.update(overrides)
    inv.update(compute_totals(inv))
    return inv


def codes(flags):
    return [f.code for f in flags]


def test_clean_invoice_has_no_flags():
    assert match_invoice(make_invoice(), make_po(), make_grns()) == []


def test_compute_totals():
    t = compute_totals(make_invoice())
    assert t == {"subtotal": 15000.0, "tax": 2100.0, "total": 17100.0}


def test_missing_po():
    flags = match_invoice(make_invoice(po_number=None), None, [])
    assert codes(flags) == [MISSING_PO]


def test_unknown_po_number_is_missing_po():
    flags = match_invoice(make_invoice(po_number="PO-404"), None, [])
    assert codes(flags) == [MISSING_PO]
    assert "PO-404" in flags[0].message


def test_price_variance_above_tolerance():
    inv = make_invoice()
    inv["lines"][0]["unit_price"] = 51.0  # +2%
    inv.update(compute_totals(inv))
    flags = match_invoice(inv, make_po(), make_grns())
    assert codes(flags) == [PRICE_VARIANCE]
    assert flags[0].details["variance_pct"] == 2.0
    assert flags[0].details["variance_amount"] == 100.0
    assert flags[0].severity == "medium"


def test_price_variance_within_tolerance_is_ignored():
    inv = make_invoice()
    inv["lines"][0]["unit_price"] = 50.2  # +0.4%
    inv.update(compute_totals(inv))
    assert match_invoice(inv, make_po(), make_grns()) == []


def test_large_price_variance_is_high_severity():
    inv = make_invoice()
    inv["lines"][0]["unit_price"] = 58.0  # +16%
    inv.update(compute_totals(inv))
    assert match_invoice(inv, make_po(), make_grns())[0].severity == "high"


def test_qty_mismatch_partial_receipt():
    flags = match_invoice(make_invoice(), make_po(), make_grns(qa=60))
    assert codes(flags) == [QTY_MISMATCH]
    assert flags[0].details["received_qty"] == 60
    assert flags[0].details["received_pct"] == 60.0


def test_qty_mismatch_sums_multiple_grns():
    grns = make_grns(qa=60) + [{"grn_number": "GRN-2", "po_number": "PO-1", "date": "2026-09-08",
                                "lines": [{"sku": "A", "qty_received": 40}]}]
    assert match_invoice(make_invoice(), make_po(), grns) == []


def test_qty_over_po():
    inv = make_invoice()
    inv["lines"][1]["qty"] = 12
    inv.update(compute_totals(inv))
    flags = match_invoice(inv, make_po(), make_grns(qb=12))
    assert codes(flags) == [QTY_MISMATCH]
    assert "PO quantity is 10" in flags[0].message


def test_tax_mismatch():
    inv = make_invoice()
    inv["lines"][1]["gst_rate"] = 18
    inv.update(compute_totals(inv))
    flags = match_invoice(inv, make_po(), make_grns())
    assert codes(flags) == [TAX_MISMATCH]
    assert flags[0].details["excess_tax"] == 600.0


def test_unexpected_freight_line_reports_pct():
    inv = make_invoice()
    inv["lines"].append({"sku": "FREIGHT", "description": "Freight", "qty": 1, "unit_price": 225.0,
                         "gst_rate": 18})
    inv.update(compute_totals(inv))
    flags = match_invoice(inv, make_po(), make_grns())
    assert codes(flags) == [UNEXPECTED_LINE]
    assert flags[0].details["pct_of_goods"] == 1.5


def test_total_mismatch_rounding():
    inv = make_invoice()
    inv["total"] = inv["total"] + 0.4
    flags = match_invoice(inv, make_po(), make_grns())
    assert codes(flags) == [TOTAL_MISMATCH]
    assert flags[0].severity == "low"
    assert flags[0].details["difference"] == 0.4


def test_total_mismatch_large_is_high():
    inv = make_invoice()
    inv["total"] = inv["total"] + 500
    assert match_invoice(inv, make_po(), make_grns())[0].severity == "high"


def test_duplicate_with_altered_number():
    original = make_invoice()
    dup = make_invoice(id="INV-2", invoice_number="DST/26-27/0100-A")
    flags = match_invoice(dup, make_po(), make_grns(), prior_invoices=[original])
    assert codes(flags) == [DUPLICATE]
    assert flags[0].details["duplicate_of"] == "INV-1"


def test_duplicate_ignores_other_vendors_and_amounts():
    original = make_invoice()
    other_vendor = make_invoice(id="INV-2", vendor_id="V02")
    assert match_invoice(other_vendor, make_po(), make_grns(), [original]) == []
    different_amount = make_invoice(id="INV-3")
    different_amount["total"] += 5000
    assert DUPLICATE not in codes(match_invoice(different_amount, make_po(), make_grns(), [original]))


def test_invoice_does_not_duplicate_itself():
    inv = make_invoice()
    assert match_invoice(inv, make_po(), make_grns(), prior_invoices=[inv]) == []


@pytest.mark.parametrize("a,b,expected", [
    ("LHM/26-27/0099", "LHM/26-27/0099-A", True),     # suffix added
    ("LHM/26-27/0099", "lhm-26-27-0099", True),       # punctuation / case
    ("INV0412", "IMV0412", True),                     # letter typo, same digits
    ("NIT/26-27/0130", "NIT/26-27/0131", False),      # consecutive fixed-fee bills
    ("ABC/1", "XYZ/9", False),
])
def test_invoice_number_similarity(a, b, expected):
    assert invoice_numbers_similar(a, b) is expected


def test_multiple_flags_together():
    inv = make_invoice(invoice_number="X-1")
    inv["lines"][0]["unit_price"] = 52.0
    inv["lines"][1]["gst_rate"] = 18
    inv["lines"].append({"sku": "FREIGHT", "description": "Freight", "qty": 1, "unit_price": 300.0,
                         "gst_rate": 18})
    inv.update(compute_totals(inv))
    inv["total"] = round(inv["total"])
    flags = match_invoice(inv, make_po(), make_grns(qa=50))
    assert set(codes(flags)) == {PRICE_VARIANCE, TAX_MISMATCH, QTY_MISMATCH, UNEXPECTED_LINE} | (
        {TOTAL_MISMATCH} if abs(inv["total"] - compute_totals(inv)["total"]) > 0.01 else set())
