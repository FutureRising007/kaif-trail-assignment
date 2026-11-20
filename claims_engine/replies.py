"""Customer reply drafts. SOP §7: every reply states the decision and the reason."""
from __future__ import annotations

SIGNATURE = "\n\nRegards,\nRouteMax Claims Team"


def _inr(amount: int) -> str:
    return f"Rs {amount:,}"


def draft_reply(decision: str, shipment_id: str, amount: int, reason: str) -> str:
    ref = f"shipment {shipment_id}" if shipment_id else "your shipment"
    bodies = {
        "approve": f"Your claim for {ref} has been approved for {_inr(amount)}. "
                   f"Reason: {reason}. The payment will be processed in the next settlement cycle.",
        "reject": f"We are unable to approve your claim for {ref}. Reason: {reason}. "
                  f"If you have further evidence, please reply to this email.",
        "need_info": f"We have received your claim for {ref}, but we need more information before we "
                     f"can decide: {reason}. Please reply with the details and we will process it promptly.",
        "escalate": f"We have received your claim for {ref}. Because of its value it is under review by "
                    f"our Claims Manager. Reason: {reason}. We will update you shortly.",
        "duplicate": f"Thank you for following up on {ref}. This claim has already been handled: {reason}. "
                     f"If you have not received the funds, please check with your accounts team using "
                     f"this reference; we are happy to help trace it.",
        "not_a_claim": f"Thank you for your email about {ref}. This is not a claim, so we have forwarded "
                       f"your request ({reason}) to our customer service team, who will respond shortly.",
    }
    if decision not in bodies:
        raise ValueError(f"unknown decision {decision!r}")
    return "Dear Customer,\n\n" + bodies[decision] + SIGNATURE
