"""Daily run: emails + shipments + history -> results.csv, team_alerts.csv, llm_audit.csv."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from .arbiter import AuditRecord, adjudicate
from .config import RulesConfig
from .email_parser import extract_claims
from .llm_reviewer import NullReviewer, Reviewer
from .loaders import load_emails, load_past_decisions, load_shipments
from .models import APPROVAL_STATUS, Decision

RESULT_COLUMNS = ["claim_id", "shipment_id", "decision", "approved_amount_inr", "reason", "draft_reply"]
ALERT_COLUMNS = ["claim_id", "shipment_id", "customer", "decision", "approved_amount_inr", "alert"]
AUDIT_COLUMNS = ["claim_id", "shipment_id", "path", "sop_violations", "code_decision", "llm_provider",
                 "llm_decision", "llm_sop_refs", "agreement", "final_decision", "approval_status",
                 "llm_rationale"]


def process(emails, shipments, past, cfg: RulesConfig,
            reviewer: Reviewer) -> tuple[list[Decision], list[AuditRecord]]:
    seen: set[str] = set()
    decisions, audits = [], []
    for email in emails:
        for item in extract_claims(email):
            d, audit = adjudicate(item, f"Subject: {email.subject}\n\n{email.body}", email.attachments,
                                  shipments, past, seen, cfg, reviewer)
            if item.is_claim and item.shipment_id:
                seen.add(item.shipment_id)
            decisions.append(d)
            audits.append(audit)
    return decisions, audits


def _write(path: Path, header: list[str], rows) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_results(decisions: list[Decision], path: Path) -> None:
    _write(path, RESULT_COLUMNS,
           ([d.claim_id, d.shipment_id, d.decision, d.approved_amount_inr, d.reason, d.draft_reply]
            for d in decisions))


def write_alerts(decisions: list[Decision], path: Path) -> None:
    _write(path, ALERT_COLUMNS,
           ([d.claim_id, d.shipment_id, d.customer, d.decision, d.approved_amount_inr, a]
            for d in decisions for a in d.alerts))


def write_audit(audits: list[AuditRecord], path: Path) -> None:
    _write(path, AUDIT_COLUMNS,
           ([a.claim_id, a.shipment_id, a.path, "; ".join(a.violations), a.code_decision, a.llm_provider,
             a.llm_decision, "; ".join(a.llm_sop_refs), a.agreement, a.final_decision,
             APPROVAL_STATUS[a.final_decision], a.llm_rationale] for a in audits))


def run(emails_dir: Path, shipments_csv: Path, past_csv: Path, out_dir: Path,
        cfg: Optional[RulesConfig] = None, reviewer: Optional[Reviewer] = None) -> list[Decision]:
    cfg = cfg or RulesConfig()
    reviewer = reviewer or NullReviewer()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions, audits = process(load_emails(emails_dir), load_shipments(shipments_csv),
                                load_past_decisions(past_csv), cfg, reviewer)
    write_results(decisions, out_dir / "results.csv")
    write_alerts(decisions, out_dir / "team_alerts.csv")
    write_audit(audits, out_dir / "llm_audit.csv")
    return decisions
