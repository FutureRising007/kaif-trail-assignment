# Claims decision rules

Derived from `claims_sop.md` (v3), `past_decisions_oct.csv`, and Meera's verbal guidance.

## Decision flow (code + LLM)

1. **Extract with Python.** Shipment IDs (`SHP-xxxx`, typos normalised), amounts, attachments and dates
   are parsed by code and joined to `shipments.csv` on `shipment_id`.
2. **Prechecks (code only):** not a claim, unknown shipment, duplicate, no amount (R1–R3).
3. **Count SOP violations** (`violations.py`):

   | Code | SOP clause | Breach |
   |---|---|---|
   | LATE | SOP §1 Time limit | filed after the customer's window (7 days; Zenith 15) |
   | NO_PHOTO | SOP §2 Evidence | damage claim without an attachment |
   | POD_CLEAN | SOP §3 Proof of delivery | damage claim, POD signed in good condition |
   | POD_FULL_COUNT | SOP §3 Proof of delivery | shortage claim, POD confirms full count |
   | POD_NO_SHORTAGE | SOP §4 Shortage | shortage claim, POD shows no shortfall |
   | OVER_DECLARED | SOP §5 Maximum payout | amount claimed above declared value |
   | OVER_LIMIT | SOP §6 Approval limit | payable amount above Rs 50,000 |

4. **Route by count** (`arbiter.py`):
   - **0 violations:** code decides (R5/R13 below). No LLM call.
   - **1 violation:** code (rules below) and Claude decide independently. Claude never sees the code's
     answer. If they differ, **the code decision is kept** and the team is alerted.
   - **2+ violations:** `need_info`, never approved, amount 0. The reason and reply cite every SOP clause
     breached. Claude is asked too (audit only); its answer cannot change the outcome.
5. Every comparison is logged to `output/llm_audit.csv`.

## Code rules (used for 0 and 1 violation cases)

Evaluated **in this order**; the first rule that decides wins.

| # | Rule | Decision | Source |
|---|------|----------|--------|
| R1 | Email has no claim intent (no damage/shortage wording, or is a document/invoice/POD request) | `not_a_claim` | Brief |
| R2 | Shipment ID missing or not in `shipments.csv` | `need_info` (ask for a valid shipment ID) | — |
| R3 | Shipment already decided in a past claim (`past_decisions_oct.csv`) or earlier in today's batch | `duplicate` (reply quotes the earlier decision / payment ref) | C-0931 paid ref PAY-7781 |
| R4 | Filed more than the customer's window after delivery. Default **7 days**; **Zenith Retail 15 days** (key account) | `reject` | SOP §1; C-0903, C-0917, C-0922 (late small claim still rejected), C-0904/C-0911/C-0914 (Zenith 15-day window) |
| R5 | Claim amount **below Rs 5,000** (and passed R1–R4) | `approve` tagged **"GoodWill & Passes"** — photos and POD checks waived | Meera; C-0901, C-0906, C-0909, C-0918 |
| R6 | Damage claim and POD signed "received in good condition" | `reject` | SOP §3; C-0905 |
| R7 | Shortage claim and POD confirms full piece count | `reject` | SOP §3; C-0912 |
| R8 | Shortage claim and POD shows fewer pieces than shipped | approve path | SOP §4; C-0916, C-0932 |
| R9 | Shortage claim with no piece count on POD | `need_info` | — |
| R10 | Damage claim without photos (no attachment, or the email says no photo) | `need_info` (ask for photos) | SOP §2; C-0908, C-0919. An attachment present = valid photo proof (Meera) |
| R11 | Payout capped at the shipment's declared value | amount = min(claim, declared) | SOP §5; C-0907, C-0934 |
| R12 | Payout above Rs 50,000 | `escalate` to Meera (amount shown is the recommended payout, not paid) | SOP §6; C-0907, C-0915, C-0921 |
| R13 | Otherwise | `approve` | — |

## Team alerts (do not change the decision)

- **Bluewave Electronics**: decide strictly by SOP, but every Bluewave claim is flagged to the team
  (October had a sales-driven exception, C-0910). Flag text is added to `reason` and to `team_alerts.csv`.
- **Zenith Retail**: prime customer, every claim is flagged for a careful second look.
- Every `escalate` is listed for Meera.
- Claims that include consequential loss (downtime, production loss) are flagged: only goods value is payable.

## Parsing notes

- Filed date = the email `Date:` header.
- Shipment IDs are normalised (`SHP-1O10` -> `SHP-1010`; letter O typed for zero).
- One email can hold several claims (one per shipment ID); each gets its own row with the same `claim_id`.
- Hinglish shortage wording ("kam aaye", "hi mile") is recognised.
