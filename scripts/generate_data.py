"""Generate the deterministic synthetic LedgerLens dataset into data/.

Buyer: a Hyderabad (Telangana, state 36) manufacturer. August 2026 is the
historical month (clerk decisions used for seeding memory); September 2026 is
the live invoice queue.

Run:  python scripts/generate_data.py
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.rules import compute_totals, match_invoice  # noqa: E402

DATA_DIR = ROOT / "data"
BUYER_STATE = "36"
rng = random.Random(42)

# (sku, description, unit_price, gst_rate, (min_qty, max_qty))
VENDORS: list[dict[str, Any]] = [
    dict(id="V01", name="Deccan Steel Traders", short="DST", state="36", city="Hyderabad", terms="Net 30",
         category="Raw material", quirks=["FREIGHT_SMALL"], catalog=[
             ("MS-ANG-50", "MS Angle 50x50x5 mm (kg)", 68.45, 18, (400, 1500)),
             ("MS-PLT-10", "MS Plate 10 mm (kg)", 72.10, 18, (300, 1200)),
             ("TMT-12", "TMT Bar Fe500 12 mm (kg)", 61.85, 18, (500, 2000))]),
    dict(id="V02", name="Sri Venkateswara Packaging Pvt Ltd", short="SVP", state="37", city="Vijayawada",
         terms="Net 45", category="Packaging", quirks=["ROUNDING"], catalog=[
             ("BOX-5PLY", "Corrugated box 5-ply 18x12x10 in", 42.35, 18, (500, 2500)),
             ("FILM-23", "Stretch film roll 23 micron", 1185.55, 18, (10, 60)),
             ("TAPE-48", "BOPP tape 48 mm x 65 m", 38.75, 18, (200, 900))]),
    dict(id="V03", name="Bharat Electricals & Cables", short="BEC", state="27", city="Pune", terms="Net 30",
         category="Electrical", quirks=["SPLIT_SHIPMENT"], catalog=[
             ("CU-4SQ", "Copper cable 4 sq mm FRLS (m)", 58.20, 18, (500, 3000)),
             ("MCB-32DP", "MCB 32A double pole", 612.40, 18, (20, 120)),
             ("LED-40", "LED panel 40W 2x2 ft", 1349.00, 18, (20, 80))]),
    dict(id="V04", name="Kaveri Chemicals Ltd", short="KCL", state="29", city="Bengaluru", terms="Net 60",
         category="Chemicals", quirks=["GST_RATE"], gst=(12, 18), catalog=[
             ("IPA-L", "Isopropyl alcohol industrial grade (L)", 142.60, 12, (100, 600)),
             ("NAOH-KG", "Caustic soda flakes (kg)", 54.35, 12, (200, 1000)),
             ("DX40-L", "Degreasing agent DX-40 (L)", 188.90, 12, (50, 300))]),
    dict(id="V05", name="Annapurna Office Supplies", short="AOS", state="36", city="Secunderabad",
         terms="Net 15", category="Office supplies", quirks=["ROUNDING"], catalog=[
             ("A4-REAM", "A4 copier paper 75 gsm (ream)", 289.55, 12, (20, 150)),
             ("TONER-88", "Toner cartridge 88A compatible", 2450.35, 18, (4, 20)),
             ("STAT-KIT", "Stationery kit (pens, files, pads)", 364.75, 18, (10, 60))]),
    dict(id="V06", name="Godavari Polymers Pvt Ltd", short="GPP", state="37", city="Rajahmundry",
         terms="Net 45", category="Raw material", quirks=["PRICE_ESCALATION"], catalog=[
             ("HDPE-GR", "HDPE granules blow grade (kg)", 118.40, 18, (500, 2500)),
             ("PP-GR", "PP granules injection grade (kg)", 109.75, 18, (500, 2500)),
             ("MB-BLUE", "Blue masterbatch (kg)", 245.30, 18, (25, 150))]),
    dict(id="V07", name="Rajputana Textiles", short="RJT", state="08", city="Bhilwara", terms="Net 30",
         category="Textiles", quirks=["SPLIT_SHIPMENT", "FREIGHT_SMALL"], catalog=[
             ("DRILL-CT", "Cotton drill fabric 2/1 (m)", 164.25, 5, (300, 1500)),
             ("CANVAS-12", "Canvas 12 oz (m)", 212.80, 5, (200, 900)),
             ("PC-6535", "Poly-cotton 65/35 (m)", 138.60, 5, (300, 1500))]),
    dict(id="V08", name="Coromandel Engineering Works", short="CEW", state="33", city="Chennai",
         terms="Net 30", category="Machined parts", quirks=["FREIGHT_SMALL"], catalog=[
             ("BH-UCP210", "Bearing housing UCP 210", 1842.50, 18, (10, 60)),
             ("GC-4", "Gear coupling size 4", 4375.00, 18, (4, 20)),
             ("SH-EN8-40", "Shaft EN8 40 mm x 1 m", 2210.40, 18, (5, 30))]),
    dict(id="V09", name="Swift Courier Services", short="SCS", state="36", city="Hyderabad", terms="Net 7",
         category="Services", quirks=["NO_PO"], catalog=[
             ("CR-DOM", "Domestic courier consignments", 86.40, 18, (120, 400)),
             ("CR-EXP", "Express document deliveries", 142.00, 18, (30, 120))]),
    dict(id="V10", name="Malabar Spices & Foods", short="MSF", state="32", city="Kochi", terms="Net 30",
         category="Canteen", quirks=["GST_RATE"], gst=(5, 12), catalog=[
             ("TUR-KG", "Turmeric powder (kg)", 312.40, 5, (20, 80)),
             ("PEP-KG", "Black pepper whole (kg)", 684.50, 5, (10, 40)),
             ("CARD-KG", "Cardamom 7 mm (kg)", 2418.20, 5, (2, 10))]),
    dict(id="V11", name="Narmada Industrial Gases", short="NIG", state="24", city="Vadodara", terms="Net 30",
         category="Consumables", quirks=["PRICE_ESCALATION", "ROUNDING"], catalog=[
             ("O2-7M3", "Oxygen cylinder refill 7 m3", 385.65, 18, (40, 160)),
             ("AR-7M3", "Argon cylinder refill 7 m3", 1240.75, 18, (10, 50)),
             ("CO2-30", "CO2 cylinder refill 30 kg", 612.35, 18, (10, 50))]),
    dict(id="V12", name="Lakshmi Hardware Mart", short="LHM", state="36", city="Hyderabad", terms="Net 15",
         category="Hardware", quirks=["ROUNDING"], catalog=[
             ("FAST-KIT", "Fastener kit M8-M16 assorted", 845.35, 18, (10, 50)),
             ("WR-E6013", "Welding rods E6013 3.15 mm (pkt)", 1265.45, 18, (10, 40)),
             ("GLV-NIT", "Nitrile safety gloves (pair)", 96.35, 12, (100, 500))]),
    dict(id="V13", name="Ganga Paper Mills", short="GPM", state="09", city="Kanpur", terms="Net 45",
         category="Packaging", quirks=["SPLIT_SHIPMENT"], catalog=[
             ("KRAFT-120", "Kraft paper 120 gsm (kg)", 48.65, 12, (1000, 5000)),
             ("DUPLEX-300", "Duplex board 300 gsm (kg)", 62.30, 12, (800, 3000))]),
    dict(id="V14", name="Nizam IT Solutions", short="NIT", state="36", city="Hyderabad", terms="Net 30",
         category="Services", quirks=["NO_PO"], catalog=[
             ("AMC-DESK", "Desktop support AMC (monthly)", 18500.00, 18, (1, 1)),
             ("AMC-NET", "Network support AMC (monthly)", 9750.00, 18, (1, 1))]),
    dict(id="V15", name="Konark Castings", short="KNC", state="21", city="Cuttack", terms="Net 60",
         category="Raw material", quirks=["FREIGHT_SMALL", "PRICE_ESCALATION"], catalog=[
             ("CI-FG260", "CI casting FG260 (kg)", 132.45, 18, (500, 2000)),
             ("SG-500", "SG iron casting 500/7 (kg)", 158.90, 18, (300, 1500))]),
    dict(id="V16", name="Vindhya Cement Agencies", short="VCA", state="23", city="Satna", terms="Net 30",
         category="Civil", quirks=["GST_RATE"], gst=(18, 28), catalog=[
             ("OPC-53", "OPC 53 grade cement (50 kg bag)", 385.50, 18, (100, 600)),
             ("PPC-50", "PPC cement (50 kg bag)", 362.25, 18, (100, 600))]),
    dict(id="V17", name="Charminar Printing Press", short="CPP", state="36", city="Hyderabad",
         terms="Net 15", category="Printing", quirks=["ROUNDING"], catalog=[
             ("LBL-1K", "Printed product labels (per 1000)", 1245.65, 18, (10, 60)),
             ("BRO-A4", "A4 tri-fold brochure", 18.35, 18, (500, 3000))]),
    dict(id="V18", name="Brahmaputra Tea Traders", short="BTT", state="18", city="Guwahati", terms="Net 30",
         category="Canteen", quirks=["SPLIT_SHIPMENT"], catalog=[
             ("CTC-KG", "Assam CTC tea BOP (kg)", 286.40, 5, (50, 300)),
             ("GRN-KG", "Green tea leaf (kg)", 512.75, 5, (10, 60))]),
]

QUIRK_TEXT = {
    "FREIGHT_SMALL": "Bills freight as a separate line, always under 2% of goods value.",
    "ROUNDING": "Rounds invoice totals to the nearest rupee without a round-off line.",
    "SPLIT_SHIPMENT": "Ships in partial lots but invoices the full PO quantity up front.",
    "GST_RATE": "Charges the wrong GST rate on this item; issues a monthly credit note.",
    "PRICE_ESCALATION": "Contract has a commodity price escalation clause of up to 3%.",
    "NO_PO": "Recurring monthly service billed without a purchase order.",
}


def clerk_note(quirk: str, v: dict[str, Any], inv: dict[str, Any]) -> str:
    """Realistic clerk note for an approved recurring quirk."""
    name = v["name"]
    if quirk == "FREIGHT_SMALL":
        return f"Freight billed separately is agreed with {name} as long as it stays under 2% of goods value. Approve, code freight to 5120."
    if quirk == "ROUNDING":
        return f"{name} rounds totals to the nearest rupee. Difference is under INR 1, approve."
    if quirk == "SPLIT_SHIPMENT":
        return f"{name} ships in partial lots; balance GRN follows within a week. OK to approve against PO quantity."
    if quirk == "GST_RATE":
        a, b = v["gst"]
        return f"{name} bills {b}% GST instead of {a}% on this item and issues a credit note every month. Approve, credit note expected."
    if quirk == "PRICE_ESCALATION":
        return f"{name} contract allows commodity price escalation up to 3%. Variance within clause, approve."
    if quirk == "NO_PO":
        return f"{name} is a recurring monthly service billed without a PO; confirmed with facilities. Approve."
    raise ValueError(quirk)


# --- GSTIN -------------------------------------------------------------------
_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_checksum(body: str) -> str:
    """Standard GSTIN mod-36 check character for the first 14 characters."""
    total = 0
    for i, ch in enumerate(body):
        p = _GST_CHARS.index(ch) * (2 if i % 2 else 1)
        total += p // 36 + p % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def make_gstin(state: str, name: str) -> str:
    letters = "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") for _ in range(3))
    pan = f"{letters}C{name[0].upper()}{rng.randint(1000, 9999)}{rng.choice('ABCDEFGHJKLMNPRTUVWXYZ')}"
    body = f"{state}{pan}1Z"
    return body + gstin_checksum(body)


# --- documents ----------------------------------------------------------------
counters = {"po": 0, "grn": 0}


def next_id(kind: str, prefix: str) -> str:
    counters[kind] += 1
    return f"{prefix}-{counters[kind]:04d}"


def build_documents(
    v: dict[str, Any], inv_date: date, seq: int, quirks: list[str], freight_pct: float | None = None
) -> tuple[dict, dict | None, list[dict]]:
    """Build (invoice, po, grns) for one vendor invoice exhibiting ``quirks``."""
    n_lines = rng.randint(1, min(3, len(v["catalog"])))
    items = rng.sample(v["catalog"], n_lines)
    po_date = inv_date - timedelta(days=rng.randint(12, 20))
    grn_date = po_date + timedelta(days=rng.randint(4, 8))

    po_lines = [
        {"sku": sku, "description": desc, "qty": rng.randint(*qr), "unit_price": price, "gst_rate": gst}
        for sku, desc, price, gst, qr in items
    ]
    inv_lines = [dict(l) for l in po_lines]
    grn_lines = [{"sku": l["sku"], "qty_received": l["qty"]} for l in po_lines]

    if "PRICE_ESCALATION" in quirks:
        line = rng.choice(inv_lines)
        line["unit_price"] = round(line["unit_price"] * (1 + rng.uniform(1.0, 2.8) / 100), 2)
    if "GST_RATE" in quirks:
        a, b = v["gst"]
        for line in inv_lines:
            if line["gst_rate"] == a:
                line["gst_rate"] = b
    if "SPLIT_SHIPMENT" in quirks:
        i = rng.randrange(len(grn_lines))
        grn_lines[i]["qty_received"] = round(po_lines[i]["qty"] * rng.uniform(0.5, 0.7))
    if "FREIGHT_SMALL" in quirks or freight_pct is not None:
        pct = freight_pct if freight_pct is not None else rng.uniform(1.1, 1.9)
        goods = sum(l["qty"] * l["unit_price"] for l in inv_lines)
        inv_lines.append({"sku": "FREIGHT", "description": "Freight & forwarding charges", "qty": 1,
                          "unit_price": round(goods * pct / 100, 2), "gst_rate": 18})

    has_po = "NO_PO" not in quirks
    po = None
    grns: list[dict] = []
    if has_po:
        po = {"po_number": next_id("po", "PO-2026"), "vendor_id": v["id"], "date": po_date.isoformat(),
              "lines": po_lines}
        grns = [{"grn_number": next_id("grn", "GRN-2026"), "po_number": po["po_number"],
                 "date": grn_date.isoformat(), "lines": grn_lines}]

    invoice = {
        "invoice_number": f"{v['short']}/26-27/{seq:04d}",
        "vendor_id": v["id"],
        "po_number": po["po_number"] if po else None,
        "date": inv_date.isoformat(),
        "due_in": v["terms"],
        "tax_type": "CGST+SGST" if v["state"] == BUYER_STATE else "IGST",
        "lines": inv_lines,
    }
    totals = compute_totals(invoice)
    if "ROUNDING" in quirks:
        # make sure the paise are visible so rounding actually changes the total
        while abs(round(totals["total"]) - totals["total"]) < 0.1:
            inv_lines[0]["unit_price"] = round(inv_lines[0]["unit_price"] + 0.07, 2)
            totals = compute_totals(invoice)
        invoice.update(subtotal=totals["subtotal"], tax=totals["tax"], total=float(round(totals["total"])))
    else:
        invoice.update(totals)
    return invoice, po, grns


def quirks_for(v: dict[str, Any], k: int) -> list[str]:
    """Which of the vendor's quirks show up on its k-th quirky invoice."""
    q = v["quirks"]
    if len(q) > 1 and k >= 2:
        return list(q)
    return [q[k % len(q)]]


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    vendors_out, invoices, pos, grns_all, truth, history = [], [], [], [], {}, []
    seq = {v["id"]: rng.randint(80, 400) for v in VENDORS}

    for v in VENDORS:
        vendors_out.append({"id": v["id"], "name": v["name"], "gstin": make_gstin(v["state"], v["name"]),
                            "state_code": v["state"], "city": v["city"], "payment_terms": v["terms"],
                            "category": v["category"]})

    # ---- August history: two clerk-approved quirky invoices per vendor ----
    hist_raw = []
    for v in VENDORS:
        for k in range(2):
            d = date(2026, 8, rng.randint(3, 28))
            seq[v["id"]] += 1
            inv, po, grns = build_documents(v, d, seq[v["id"]], quirks_for(v, k))
            hist_raw.append((d, v, inv, po, grns, quirks_for(v, k)))
    hist_raw.sort(key=lambda r: r[0])
    for i, (d, v, inv, po, grns, qs) in enumerate(hist_raw, 1):
        inv["id"] = f"H-{i:04d}"
        flags = match_invoice(inv, po, grns)
        history.append({
            "id": inv["id"], "date": d.isoformat(), "vendor_id": v["id"],
            "invoice_number": inv["invoice_number"], "total": inv["total"],
            "flags": [f.to_dict() for f in flags], "decision": "approve",
            "note": " ".join(clerk_note(q, v, inv) for q in qs),
        })

    # ---- September queue ----
    rows = []  # (day, vendor, quirks, scenario, extra)
    for i, v in enumerate(VENDORS):
        d1 = 1 + (i * 7) % 11
        d2 = min(d1 + rng.randint(8, 11), 28)
        d3 = min(d2 + rng.randint(7, 10), 30)
        for k, day in enumerate([d1, d2, d3]):
            rows.append((day, v, quirks_for(v, k), "quirk", None))
        if i % 2 == 0 and "NO_PO" not in v["quirks"]:
            rows.append((rng.randint(3, 29), v, [], "clean", None))
    v08 = next(v for v in VENDORS if v["id"] == "V08")
    rows.append((26, v08, [], "anomaly_freight_spike", 9.6))
    rows.sort(key=lambda r: (r[0], r[1]["id"]))

    for day, v, qs, scenario, extra in rows:
        seq[v["id"]] += 1
        inv, po, grns = build_documents(v, date(2026, 9, day), seq[v["id"]], qs, freight_pct=extra)
        inv["day"] = day
        invoices.append(inv)
        if po:
            pos.append(po)
            grns_all.extend(grns)
        if scenario == "anomaly_freight_spike":
            note = (f"Freight at {extra}% of goods value is far above {v['name']}'s usual ~1.5%. "
                    "Hold and ask the vendor to justify the freight charge.")
            truth[inv["invoice_number"]] = ("hold", note, scenario)
        elif scenario == "clean":
            truth[inv["invoice_number"]] = ("approve", "Clean three-way match.", scenario)
        else:
            truth[inv["invoice_number"]] = ("approve", " ".join(clerk_note(q, v, inv) for q in qs),
                                            "quirk:" + "+".join(qs))

    # Duplicate: Lakshmi Hardware re-sends its first September invoice with a suffix.
    first_lhm = next(i for i in invoices if i["vendor_id"] == "V12")
    dup = json.loads(json.dumps(first_lhm))
    dup["invoice_number"] = first_lhm["invoice_number"] + "-A"
    dup["day"] = 24
    dup["date"] = date(2026, 9, 24).isoformat()
    invoices.append(dup)
    truth[dup["invoice_number"]] = (
        "hold", f"Same PO and amount as {first_lhm['invoice_number']} which we already processed; only a "
                "suffix was added to the number. Hold as duplicate and contact vendor.", "anomaly_duplicate")

    invoices.sort(key=lambda x: (x["day"], x["vendor_id"], x["invoice_number"]))
    ground_truth = {}
    for n, inv in enumerate(invoices, 1):
        inv["id"] = f"INV-{n:04d}"
        action, note, scenario = truth[inv["invoice_number"]]
        ground_truth[inv["id"]] = {"expected_action": action, "clerk_note": note, "scenario": scenario}
    ground_truth["_vendor_quirks"] = {
        v["id"]: [QUIRK_TEXT[q] for q in v["quirks"]] for v in VENDORS}

    files = {"vendors.json": vendors_out, "purchase_orders.json": pos, "goods_receipts.json": grns_all,
             "invoices.json": invoices, "history.json": history, "ground_truth.json": ground_truth}
    for name, payload in files.items():
        (DATA_DIR / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"vendors={len(vendors_out)} invoices={len(invoices)} pos={len(pos)} grns={len(grns_all)} "
          f"history={len(history)}")


if __name__ == "__main__":
    main()
