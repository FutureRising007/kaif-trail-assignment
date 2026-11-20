"""Two-step decision policy.

  prechecks (not a claim / unknown shipment / duplicate / no amount) -> code only
  0 SOP violations  -> code only
  1 SOP violation   -> code and LLM decide independently; code wins on disagreement
  2+ SOP violations -> need_info, never approved; reason cites every SOP clause breached
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .config import RulesConfig
from .llm_reviewer import LLMVerdict, Reviewer, ReviewCase
from .models import ClaimItem, Decision, PastDecision, Shipment
from .rules import decide, make_decision
from .violations import detect_violations

PRECHECK_RULES = {"R1", "R2", "R3"}


@dataclass
class AuditRecord:
    claim_id: str
    shipment_id: str
    path: str
    violations: list[str] = field(default_factory=list)
    code_decision: str = ""
    llm_decision: str = ""
    llm_sop_refs: list[str] = field(default_factory=list)
    llm_provider: str = ""
    agreement: str = "n/a"          # agree | disagree | llm_unavailable | n/a
    final_decision: str = ""
    llm_rationale: str = ""


def _add_alert(d: Decision, alert: str) -> None:
    d.alerts.append(alert)
    d.reason += ("; " if "TEAM ALERT:" in d.reason else " | TEAM ALERT: ") + alert


def _compare(code_decision: str, verdict: Optional[LLMVerdict]) -> str:
    if verdict is None:
        return "llm_unavailable"
    return "agree" if verdict.decision == code_decision else "disagree"


def adjudicate(item: ClaimItem, email_text: str, attachments: list[str],
               shipments: dict[str, Shipment], past: dict[str, PastDecision], seen_today: set[str],
               cfg: RulesConfig, reviewer: Reviewer) -> tuple[Decision, AuditRecord]:
    code = decide(item, shipments, past, seen_today, cfg)
    audit = AuditRecord(item.claim_id, code.shipment_id, "precheck", code_decision=code.decision)

    if code.rule in PRECHECK_RULES:
        audit.final_decision = code.decision
        return code, audit

    shipment = shipments[item.shipment_id]
    violations = detect_violations(item, shipment, cfg)
    audit.violations = [v.sop_ref for v in violations]

    if not violations:
        audit.path, audit.final_decision = "no_violation", code.decision
        return code, audit

    verdict = reviewer.review(ReviewCase(item, shipment, email_text, list(attachments)))
    if verdict:
        audit.llm_decision, audit.llm_sop_refs, audit.llm_rationale, audit.llm_provider = \
            verdict.decision, verdict.sop_refs, verdict.rationale, verdict.provider

    if len(violations) >= 2:
        breaches = "; ".join(f"{v.sop_ref}: {v.detail}" for v in violations)
        final = make_decision(
            item, shipment, "need_info", 0, "M1",
            f"the claim breaches more than one rule of our claims policy ({breaches}). "
            f"A claims officer will review it before any decision",
            cfg, extra_alerts=[f"Multiple SOP violations ({', '.join(audit.violations)}): manual review"])
        audit.path, audit.code_decision = "multi_violation", "need_info"
    else:
        final = code
        audit.path = "single_violation"

    audit.agreement = _compare(final.decision, verdict)
    if audit.agreement == "disagree":
        _add_alert(final, f"LLM said '{verdict.decision}', code said '{final.decision}': code decision kept")
    audit.final_decision = final.decision
    return final, audit
