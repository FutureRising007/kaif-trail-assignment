"""Blind back-test: decide structured past-claim rows, then score against the real decisions.

The blind file has the claim facts but no decision columns, no email body, no POD and no
declared value. The answer key (if given) is read only after deciding, for scoring.
Past decisions are NOT used as a duplicate history here, so the answers can't leak in.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Optional

from .arbiter import adjudicate
from .config import RulesConfig
from .llm_reviewer import NullReviewer, Reviewer
from .models import APPROVAL_STATUS, ClaimItem, Shipment

PAST_VOCAB = {"approve": "approved", "reject": "rejected", "escalate": "escalated",
              "need_info": "need_info", "duplicate": "duplicate", "not_a_claim": "not_a_claim"}

BASE_COLUMNS = ["claim_id", "shipment_id", "customer", "claim_type", "filed_date", "delivered_date",
                "claim_amount_inr", "photo_attached", "decision", "approved_amount_inr", "decided_by", "notes"]
EXTRA_COLUMNS = ["approval_status", "review_path", "sop_violations", "llm_provider", "llm_decision",
                 "agreement"]
SCORE_COLUMNS = ["actual_decision", "actual_amount_inr", "decision_match", "amount_match"]


def row_to_case(row: dict) -> tuple[ClaimItem, Shipment, str, list[str]]:
    sid = row["shipment_id"].strip().upper()
    amount = int(row["claim_amount_inr"])
    has_photo = row["photo_attached"].strip().lower() in ("yes", "y", "true", "1")
    ctype = row["claim_type"].strip().lower()
    item = ClaimItem(claim_id=row["claim_id"].strip(), shipment_id=sid, claim_type=ctype, amount=amount,
                     has_photo=has_photo, is_claim=True,
                     filed_date=date.fromisoformat(row["filed_date"].strip()), text="")
    shipment = Shipment(sid, row["customer"].strip(), date.fromisoformat(row["delivered_date"].strip()),
                        0, 0, "Not available", "", pod_available=False, declared_known=False)
    text = (f"{ctype.capitalize()} claim for {sid} from {shipment.customer}. Amount claimed Rs {amount:,}. "
            f"Photo attached: {'yes' if has_photo else 'no'}. "
            f"(Structured claim record: no email body, POD or declared value available.)")
    return item, shipment, text, (["photo_on_file"] if has_photo else [])


def _load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def run_blind(blind_csv: Path, out_csv: Path, answer_csv: Optional[Path] = None,
              reviewer: Optional[Reviewer] = None, cfg: Optional[RulesConfig] = None):
    cfg = cfg or RulesConfig()
    reviewer = reviewer or NullReviewer()
    answers = {r["claim_id"].strip(): r for r in _load(answer_csv)} if answer_csv else {}

    rows, seen = [], set()
    for src in _load(blind_csv):
        item, shipment, text, attachments = row_to_case(src)
        d, audit = adjudicate(item, text, attachments, {shipment.shipment_id: shipment}, {}, seen, cfg, reviewer)
        seen.add(shipment.shipment_id)

        decided_by = "auto: code"
        if audit.llm_provider:
            decided_by += f" + {audit.llm_provider} ({audit.agreement})"
        elif audit.agreement == "llm_unavailable":
            decided_by += " (LLM unavailable)"
        row = {c: src.get(c, "") for c in BASE_COLUMNS}
        row.update(decision=PAST_VOCAB[d.decision], approved_amount_inr=d.approved_amount_inr,
                   decided_by=decided_by, notes=d.reason,
                   approval_status=APPROVAL_STATUS[d.decision], review_path=audit.path,
                   sop_violations="; ".join(audit.violations), llm_provider=audit.llm_provider,
                   llm_decision=audit.llm_decision, agreement=audit.agreement)
        if item.claim_id in answers:
            a = answers[item.claim_id]
            actual_amt = int(a.get("approved_amount_inr") or 0)
            row.update(actual_decision=a["decision"].strip(), actual_amount_inr=actual_amt,
                       decision_match="yes" if a["decision"].strip() == row["decision"] else "no",
                       amount_match="yes" if actual_amt == d.approved_amount_inr else "no")
        rows.append(row)

    columns = BASE_COLUMNS + EXTRA_COLUMNS + (SCORE_COLUMNS if answers else [])
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)

    summary = {"claims": len(rows),
               "llm_consulted": sum(1 for r in rows if r["agreement"] != "n/a"),
               "llm_agree": sum(1 for r in rows if r["agreement"] == "agree"),
               "llm_disagree": sum(1 for r in rows if r["agreement"] == "disagree"),
               "llm_unavailable": sum(1 for r in rows if r["agreement"] == "llm_unavailable")}
    if answers:
        summary["decision_matches"] = sum(1 for r in rows if r.get("decision_match") == "yes")
        summary["amount_matches"] = sum(1 for r in rows if r.get("amount_match") == "yes")
    return rows, summary
