"""Turn a raw .txt email into structured ClaimItems.

Deterministic regex extraction: auditable and free to run. The `extract_claims`
signature is the seam where an LLM extractor can be dropped in later for messier
inboxes (see README "Next steps").
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .models import ClaimItem, Email

_SHP_RE = re.compile(r"\bSHP[\s\-_]*([0-9Oo]{3,})\b", re.I)
_AMOUNT_RE = re.compile(r"(?:Rs\.?|INR|₹)\s*([\d,]+)", re.I)

_SHORTAGE_RE = re.compile(
    r"shortage|missing|\bshort\b|received only|only \d+ of \d+|"
    r"kam aa[yi]|hi mile|nahi mile|nahi aaye", re.I)
_DAMAGE_RE = re.compile(
    r"damag|dent|crush|stain|\bwet\b|broke|scratch|\btorn\b|\btore\b|\bbent\b|"
    r"crack|spoil|rust|leak", re.I)
_NO_PHOTO_RE = re.compile(r"\bno (?:photo|picture|image|pic)s?\b|without (?:photo|picture)s?", re.I)
_CONSEQUENTIAL_RE = re.compile(
    r"downtime|production loss|loss of (?:business|production)|consequential|lost sales", re.I)
_FOLLOW_UP_RE = re.compile(r"follow(?:ing)?[\s-]?up|still (?:not|haven'?t)|reminder|not (?:yet )?paid", re.I)


def normalize_shipment_id(raw: str) -> str:
    m = _SHP_RE.search(raw)
    digits = (m.group(1) if m else raw).replace("O", "0").replace("o", "0")
    return f"SHP-{digits}"


def parse_amount(text: str) -> Optional[int]:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    digits = m.group(1).replace(",", "")
    return int(digits) if digits else None


def detect_claim_type(text: str) -> Optional[str]:
    if _SHORTAGE_RE.search(text):
        return "shortage"
    if _DAMAGE_RE.search(text):
        return "damage"
    return None


def parse_email(raw: str, claim_id: str) -> Email:
    head, _, body = raw.replace("\r\n", "\n").partition("\n\n")
    headers: dict[str, str] = {}
    for line in head.splitlines():
        key, sep, val = line.partition(":")
        if sep:
            headers[key.strip().lower()] = val.strip()
    att_raw = headers.get("attachments", "")
    attachments = [] if att_raw.lower() in ("", "none", "nil", "-") else \
        [a.strip() for a in att_raw.split(",") if a.strip()]
    filed = datetime.strptime(headers["date"][:10], "%Y-%m-%d").date()
    return Email(claim_id=claim_id, sender=headers.get("from", ""), filed_date=filed,
                 subject=headers.get("subject", ""), attachments=attachments, body=body.strip())


def is_claim_email(email: Email) -> bool:
    return detect_claim_type(f"{email.subject}\n{email.body}") is not None


def _shipment_ids_in_order(text: str) -> list[tuple[str, int]]:
    seen: dict[str, int] = {}
    for m in _SHP_RE.finditer(text):
        sid = normalize_shipment_id(m.group(0))
        seen.setdefault(sid, m.start())
    return sorted(seen.items(), key=lambda kv: kv[1])


def _segments(email: Email) -> list[tuple[Optional[str], str]]:
    """Split the email into (shipment_id, text) chunks, one per claimed shipment."""
    body_ids = _shipment_ids_in_order(email.body)
    if len(body_ids) <= 1:
        ids = body_ids or _shipment_ids_in_order(email.subject)
        sid = ids[0][0] if ids else None
        return [(sid, f"{email.subject}\n{email.body}")]
    chunks = []
    for i, (sid, start) in enumerate(body_ids):
        end = body_ids[i + 1][1] if i + 1 < len(body_ids) else len(email.body)
        chunks.append((sid, email.body[start:end]))
    return chunks


def extract_claims(email: Email) -> list[ClaimItem]:
    full = f"{email.subject}\n{email.body}"
    claim_email = is_claim_email(email)
    items = []
    for sid, text in _segments(email):
        has_photo = bool(email.attachments) and not _NO_PHOTO_RE.search(text)
        items.append(ClaimItem(
            claim_id=email.claim_id,
            shipment_id=sid,
            claim_type=detect_claim_type(text) or (detect_claim_type(full) if claim_email else None),
            amount=parse_amount(text),
            has_photo=has_photo,
            is_claim=claim_email,
            filed_date=email.filed_date,
            consequential_loss=bool(_CONSEQUENTIAL_RE.search(text)),
            is_follow_up=bool(email.subject.lower().startswith("re:") or _FOLLOW_UP_RE.search(full)),
            text=text.strip(),
        ))
    return items
