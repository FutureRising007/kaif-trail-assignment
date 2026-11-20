"""Independent LLM review of a claim against the SOP.

The LLM never sees the code's decision. Its verdict is compared with the code's in
`arbiter.py`; on any disagreement, error, or refusal the code decision stands.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol

from .config import RulesConfig
from .models import DECISIONS, ClaimItem, Shipment
from .violations import SOP

log = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(DECISIONS)},
        "sop_refs": {"type": "array", "items": {"type": "string", "enum": list(SOP.values())}},
        "rationale": {"type": "string"},
    },
    "required": ["decision", "sop_refs", "rationale"],
    "additionalProperties": False,
}


@dataclass
class ReviewCase:
    item: ClaimItem
    shipment: Shipment
    email_text: str
    attachments: list[str] = field(default_factory=list)


@dataclass
class LLMVerdict:
    decision: str
    sop_refs: list[str]
    rationale: str
    provider: str = field(default="", compare=False)


class Reviewer(Protocol):
    def review(self, case: ReviewCase) -> Optional[LLMVerdict]: ...


class NullReviewer:
    """No LLM available: the arbiter falls back to the code decision."""

    def review(self, case: ReviewCase) -> Optional[LLMVerdict]:
        return None


def build_system_prompt(sop_text: str, cfg: RulesConfig) -> str:
    windows = ", ".join(f"{c}: {d} days" for c, d in cfg.customer_window_days.items())
    return f"""You review damage and shortage claims for RouteMax Logistics.
Decide one claim strictly from the SOP and house rules below, using only the facts given.

<sop>
{sop_text.strip()}
</sop>

<house_rules>
- Filing window is {cfg.default_window_days} days, except key accounts ({windows}).
- An email attachment counts as photo proof. "Photos attached" in the text with no attachment is not proof.
- Claims strictly below Rs {cfg.goodwill_threshold_inr:,} that are on time are approved as goodwill even without photos.
- Payout is capped at the declared value. Payable amounts above Rs {cfg.manager_limit_inr:,} are escalated to the Claims Manager.
- If the claim breaches two or more SOP clauses, decide need_info and do not approve.
</house_rules>

Decisions: approve, reject, need_info (missing information or multiple SOP breaches), escalate
(needs the Claims Manager), duplicate, not_a_claim.
In sop_refs list every SOP clause the claim breaches, using the exact labels {list(SOP.values())}.
Keep the rationale to one or two sentences."""


def build_user_prompt(case: ReviewCase) -> str:
    it, s = case.item, case.shipment
    days = (it.filed_date - s.delivered_date).days
    amount = f"Rs {it.amount:,}" if it.amount is not None else "not stated"
    return f"""<shipment>
shipment_id: {s.shipment_id}
customer: {s.customer}
delivered_date: {s.delivered_date.isoformat()}
pieces_shipped: {s.pieces_shipped}
declared_value_inr: {f"{s.declared_value:,}" if s.declared_known else "not on record"}
pod_status: {s.pod_status if s.pod_available else "not on record (do not assume a clean POD)"}
pod_remarks: {(s.pod_remarks or "(none)") if s.pod_available else "not on record"}
</shipment>

<claim>
filed_date: {it.filed_date.isoformat()} ({days} days after delivery)
claim_type: {it.claim_type or "unknown"}
amount_claimed: {amount}
attachments: {", ".join(case.attachments) if case.attachments else "none"}
</claim>

<email>
{case.email_text.strip()}
</email>

Decide this claim for shipment {s.shipment_id}."""


class ClaudeReviewer:
    def __init__(self, sop_text: str, cfg: RulesConfig, client=None, model: str = MODEL,
                 effort: str = "medium"):
        if client is None:
            import anthropic  # optional dependency, imported only when the LLM is used
            client = anthropic.Anthropic()
        self.client, self.model, self.effort = client, model, effort
        self.system = build_system_prompt(sop_text, cfg)

    def review(self, case: ReviewCase) -> Optional[LLMVerdict]:
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=self.system,
                messages=[{"role": "user", "content": build_user_prompt(case)}],
                output_config={"effort": self.effort,
                               "format": {"type": "json_schema", "schema": VERDICT_SCHEMA}},
            )
        except Exception as e:  # any API failure -> code decision stands
            log.warning("LLM review failed for %s: %s: %s", case.item.claim_id, type(e).__name__, e)
            return None

        if resp.stop_reason in ("refusal", "max_tokens"):
            log.warning("LLM review for %s stopped: %s", case.item.claim_id, resp.stop_reason)
            return None
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.warning("LLM review for %s returned invalid JSON", case.item.claim_id)
            return None
        if data.get("decision") not in DECISIONS:
            return None
        return LLMVerdict(data["decision"], list(data.get("sop_refs", [])), data.get("rationale", ""),
                          provider=f"claude:{self.model}")
