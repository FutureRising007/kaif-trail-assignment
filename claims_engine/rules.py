"""Ordered decision rules. See RULES.md for the source of each rule."""
from __future__ import annotations

from typing import Optional

from .config import RulesConfig
from .models import ClaimItem, Decision, PastDecision, Shipment
from .replies import draft_reply


def _inr(n: int) -> str:
    return f"Rs {n:,}"


def _alerts_for(shipment: Optional[Shipment], item: ClaimItem, cfg: RulesConfig) -> list[str]:
    alerts = []
    if shipment and shipment.customer in cfg.alert_customers:
        alerts.append(cfg.alert_customers[shipment.customer])
    if shipment and not shipment.pod_available:
        alerts.append("POD not on record: verify proof of delivery before payment")
    if item.consequential_loss:
        alerts.append("Claim includes consequential loss (e.g. downtime); only goods value is payable")
    return alerts


def _make(item, shipment, decision, amount, rule, reason, cfg, extra_alerts=()):
    alerts = _alerts_for(shipment, item, cfg) + list(extra_alerts)
    internal = f"[{rule}] {reason}"
    if alerts:
        internal += " | TEAM ALERT: " + "; ".join(alerts)
    sid = item.shipment_id or ""
    return Decision(
        claim_id=item.claim_id, shipment_id=sid, decision=decision, approved_amount_inr=amount,
        reason=internal, draft_reply=draft_reply(decision, sid, amount, reason), rule=rule,
        customer=shipment.customer if shipment else "", alerts=alerts,
    )


make_decision = _make  # public builder, used by the arbiter


def decide(item: ClaimItem, shipments: dict[str, Shipment], past: dict[str, PastDecision],
           seen_today: set[str], cfg: RulesConfig) -> Decision:
    shipment = shipments.get(item.shipment_id) if item.shipment_id else None

    # R1 not a claim
    if not item.is_claim:
        return _make(item, shipment, "not_a_claim", 0, "R1",
                     "request for documents/information, no damage or shortage reported", cfg)

    # R2 unknown shipment
    if shipment is None:
        what = f"shipment {item.shipment_id} was not found in our records" if item.shipment_id \
            else "no shipment ID was given"
        return _make(item, None, "need_info", 0, "R2",
                     f"{what}; please share the correct shipment ID", cfg)

    # R3 duplicate
    prior = past.get(shipment.shipment_id)
    if prior:
        detail = f"claim {prior.claim_id} was already {prior.decision}"
        if prior.approved_amount:
            detail += f" for {_inr(prior.approved_amount)}"
        if prior.notes:
            detail += f" ({prior.notes})"
        return _make(item, shipment, "duplicate", 0, "R3", detail, cfg)
    if shipment.shipment_id in seen_today:
        return _make(item, shipment, "duplicate", 0, "R3",
                     "a claim for this shipment was already received today", cfg)

    # R4 time window
    days = (item.filed_date - shipment.delivered_date).days
    window = cfg.customer_window_days.get(shipment.customer, cfg.default_window_days)
    if days > window:
        return _make(item, shipment, "reject", 0, "R4",
                     f"filed {days} days after delivery; the limit is {window} days", cfg)

    if item.amount is None:
        return _make(item, shipment, "need_info", 0, "R2",
                     "the claim amount was not stated; please confirm the amount claimed", cfg)

    # R5 goodwill
    if item.amount < cfg.goodwill_threshold_inr:
        amt = shipment.payable(item.amount)
        return _make(item, shipment, "approve", amt, "R5",
                     f"GoodWill & Passes: small claim under {_inr(cfg.goodwill_threshold_inr)}, "
                     f"filed {days} days after delivery", cfg)

    # R6/R7 POD contradicts the claim
    if item.claim_type == "damage" and shipment.pod_clean:
        return _make(item, shipment, "reject", 0, "R6",
                     "the proof of delivery was signed as received in good condition with no remarks", cfg)
    received = shipment.received_count
    if item.claim_type == "shortage" and not shipment.pod_available:
        basis = "shortage claim; POD not available in this record"
    elif item.claim_type == "shortage":
        if received is not None and received >= shipment.pieces_shipped:
            return _make(item, shipment, "reject", 0, "R7",
                         f"the proof of delivery confirms the full count of "
                         f"{shipment.pieces_shipped} pieces was received", cfg)
        if received is None:  # R9
            return _make(item, shipment, "need_info", 0, "R9",
                         "the proof of delivery does not record a piece shortage; please share the "
                         "delivery note or signed shortage remark", cfg)
        basis = f"POD shows {received} of {shipment.pieces_shipped} pieces received"  # R8
    else:
        # R10 photos
        if not item.has_photo:
            return _make(item, shipment, "need_info", 0, "R10",
                         "photos of the damaged goods are required to assess a damage claim", cfg)
        basis = (f"damage supported by photos and POD remark '{shipment.pod_remarks}'"
                 if shipment.pod_available else "damage supported by photos; POD not available in this record")

    # R11 cap
    amount = shipment.payable(item.amount)
    if amount < item.amount:
        basis += f"; capped at the declared value of {_inr(shipment.declared_value)} " \
                 f"(claimed {_inr(item.amount)})"

    # R12 manager approval
    if amount > cfg.manager_limit_inr:
        return _make(item, shipment, "escalate", amount, "R12",
                     f"{basis}; payout above {_inr(cfg.manager_limit_inr)} needs Claims Manager approval",
                     cfg, extra_alerts=[f"Needs {cfg.manager_name}'s approval: recommended {_inr(amount)}"])

    return _make(item, shipment, "approve", amount, "R13", f"{basis}, filed {days} days after delivery", cfg)
