"""Which SOP clauses a claim breaches. Counting them drives the code-vs-LLM review path."""
from __future__ import annotations

from dataclasses import dataclass

from .config import RulesConfig
from .models import ClaimItem, Shipment

SOP = {
    1: "SOP §1 Time limit",
    2: "SOP §2 Evidence",
    3: "SOP §3 Proof of delivery",
    4: "SOP §4 Shortage",
    5: "SOP §5 Maximum payout",
    6: "SOP §6 Approval limit",
}


@dataclass(frozen=True)
class Violation:
    code: str
    sop_ref: str
    detail: str


def _inr(n: int) -> str:
    return f"Rs {n:,}"


def detect_violations(item: ClaimItem, shipment: Shipment, cfg: RulesConfig) -> list[Violation]:
    """Return SOP breaches in SOP order. Assumes prechecks (claim, shipment, amount) passed."""
    out: list[Violation] = []
    days = (item.filed_date - shipment.delivered_date).days
    window = cfg.customer_window_days.get(shipment.customer, cfg.default_window_days)
    if days > window:
        out.append(Violation("LATE", SOP[1], f"filed {days} days after delivery; the limit is {window} days"))

    if item.claim_type == "damage":
        if not item.has_photo:
            out.append(Violation("NO_PHOTO", SOP[2], "no photos of the damaged goods were provided"))
        if shipment.pod_available and shipment.pod_clean:
            out.append(Violation("POD_CLEAN", SOP[3],
                                 "POD signed as received in good condition with no remarks"))
    elif item.claim_type == "shortage" and shipment.pod_available:
        received = shipment.received_count
        if received is not None and received >= shipment.pieces_shipped:
            out.append(Violation("POD_FULL_COUNT", SOP[3],
                                 f"POD confirms the full count of {shipment.pieces_shipped} pieces"))
        elif received is None:
            out.append(Violation("POD_NO_SHORTAGE", SOP[4], "POD remarks do not record fewer pieces than shipped"))

    amount = item.amount or 0
    if shipment.declared_known and amount > shipment.declared_value:
        out.append(Violation("OVER_DECLARED", SOP[5],
                             f"claimed {_inr(amount)} exceeds the declared value of {_inr(shipment.declared_value)}"))
    payable = shipment.payable(amount)
    if payable > cfg.manager_limit_inr:
        out.append(Violation("OVER_LIMIT", SOP[6],
                             f"payable {_inr(payable)} is above the {_inr(cfg.manager_limit_inr)} approval limit"))
    return out
