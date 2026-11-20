"""Plain data objects shared across the engine."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

DECISIONS = ("approve", "reject", "need_info", "escalate", "duplicate", "not_a_claim")

APPROVAL_STATUS = {
    "approve": "APPROVED",
    "escalate": "PENDING MANAGER APPROVAL",
    "reject": "NOT APPROVED",
    "need_info": "ON HOLD - INFO REQUESTED",
    "duplicate": "ALREADY PROCESSED",
    "not_a_claim": "N/A",
}

_COUNT_RE = re.compile(r"(\d+)\s*(?:pieces?|pcs|units?|cartons?|boxes?)?\s*received", re.I)


@dataclass
class Email:
    claim_id: str
    sender: str
    filed_date: date
    subject: str
    attachments: list[str]
    body: str


@dataclass
class ClaimItem:
    """One claim (one shipment) extracted from an email."""
    claim_id: str
    shipment_id: Optional[str]
    claim_type: Optional[str]          # "damage" | "shortage" | None
    amount: Optional[int]
    has_photo: bool
    is_claim: bool
    filed_date: date
    consequential_loss: bool = False
    is_follow_up: bool = False
    text: str = ""


@dataclass
class Shipment:
    shipment_id: str
    customer: str
    delivered_date: date
    pieces_shipped: int
    declared_value: int
    pod_status: str
    pod_remarks: str
    pod_available: bool = True      # False when the record has no POD (e.g. blind test rows)
    declared_known: bool = True     # False when the declared value is not on record

    @property
    def pod_clean(self) -> bool:
        return self.pod_available and "good condition" in self.pod_status.lower()

    def payable(self, amount: int) -> int:
        return min(amount, self.declared_value) if self.declared_known else amount

    @property
    def received_count(self) -> Optional[int]:
        m = _COUNT_RE.search(self.pod_remarks or "")
        return int(m.group(1)) if m else None


@dataclass
class PastDecision:
    claim_id: str
    shipment_id: str
    decision: str
    approved_amount: int
    notes: str


@dataclass
class Decision:
    claim_id: str
    shipment_id: str
    decision: str
    approved_amount_inr: int
    reason: str
    draft_reply: str
    rule: str
    customer: str = ""
    alerts: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.decision not in DECISIONS:
            raise ValueError(f"invalid decision {self.decision!r}")
