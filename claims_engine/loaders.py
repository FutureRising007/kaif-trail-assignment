"""Read the daily inputs."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .email_parser import parse_email
from .models import Email, PastDecision, Shipment


def load_shipments(path: Path) -> dict[str, Shipment]:
    out: dict[str, Shipment] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r["shipment_id"].strip().upper()
            out[sid] = Shipment(
                shipment_id=sid,
                customer=r["customer"].strip(),
                delivered_date=date.fromisoformat(r["delivered_date"].strip()),
                pieces_shipped=int(r["pieces_shipped"]),
                declared_value=int(r["declared_value_inr"]),
                pod_status=r["pod_status"].strip(),
                pod_remarks=(r.get("pod_remarks") or "").strip(),
            )
    return out


def load_past_decisions(path: Path) -> dict[str, PastDecision]:
    out: dict[str, PastDecision] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r["shipment_id"].strip().upper()
            out[sid] = PastDecision(
                claim_id=r["claim_id"].strip(),
                shipment_id=sid,
                decision=r["decision"].strip(),
                approved_amount=int(r["approved_amount_inr"] or 0),
                notes=(r.get("notes") or "").strip(),
            )
    return out


def load_emails(directory: Path) -> list[Email]:
    files = sorted(Path(directory).glob("*.txt"))
    return [parse_email(p.read_text(encoding="utf-8"), p.stem) for p in files]
