# RouteMax claims desk automation

Reads the day's claim emails, checks them against `shipments.csv` and last month's
decisions, and writes a review sheet plus a team-alert list. Python code extracts and decides;
an LLM cross-checks claims that breach an SOP clause (**OpenAI primary, Gemini fallback**), and code wins
any disagreement.
See `RULES.md` for the decision flow.

The core runs on the Python 3.10+ stdlib. For the LLM cross-check, use the project `.venv`
(SDKs installed from `requirements.txt`) and copy `.env.example` to `.env` with `OPENAI_API_KEY`
and `GEMINI_API_KEY`. A provider without a key is skipped; with none, the run is code-only and the CLI says so.

```
.venv\Scripts\python.exe run_claims.py            # today's emails -> output/
.venv\Scripts\python.exe run_blind_test.py         # October blind back-test -> output/blind_test_results.csv
python run_claims.py --no-llm                     # code only
python run_claims.py --llm gemini,openai          # change provider order (claude also supported)
python run_claims.py --emails D --shipments S.csv --past P.csv --sop SOP.md --out OUT
python -m unittest discover -s tests -t .   # 130 unit + 16 integration tests, no API calls
```

**Outputs**
- `output/results.csv`: `claim_id, shipment_id, decision, approved_amount_inr, reason, draft_reply`
- `output/team_alerts.csv`: Bluewave, Zenith, escalations, multi-violation claims, code/LLM disagreements
- `output/llm_audit.csv`: per claim: path, SOP violations, code decision, LLM decision, agreement

**Layout**
| File | Role |
|---|---|
| `RULES.md` | The rulebook (SOP + Oct precedents + Meera's guidance), in evaluation order |
| `claims_engine/config.py` | Knobs: windows, goodwill threshold, manager limit, alert customers |
| `claims_engine/email_parser.py` | Headers, shipment IDs (typo fix), amounts, claim type, photos, multi-claim split |
| `claims_engine/rules.py` | Ordered decision rules R1–R13; every reason is tagged with its rule ID |
| `claims_engine/violations.py` | Which SOP clauses (§1–§6) a claim breaches |
| `claims_engine/llm_reviewer.py` | Shared prompts + JSON verdict schema; Claude reviewer |
| `claims_engine/llm_providers.py` | OpenAI (primary) -> Gemini (fallback) chain; each fails closed |
| `claims_engine/blind.py` | Blind back-test: decide structured rows, mark approval status, score vs answers |
| `claims_engine/arbiter.py` | 0 / 1 / 2+ violation routing; code wins disagreements |
| `claims_engine/replies.py` | Customer reply templates (decision + reason) |
| `claims_engine/pipeline.py` | Orchestration and CSV writers |

## Judgment calls to confirm with Meera
1. **Two violations become need_info, even when one would be a clear reject or escalate.** C06 (above declared value + above Rs 50k) was escalate; C12 (late + no photo) was reject. Both are now need_info, as specified.
1a. **Confirmed:** "above declared value" (SOP §5) counts as a violation, so C06 (§5 + §6) stays need_info.
2. **Goodwill (< Rs 5,000) waives the photo and POD checks** but not the time limit or duplicate checks (C04, C10, C14/SHP-1015).
3. **Bluewave is decided strictly by SOP** and flagged. C02 (11 days late) is rejected, though Oct shows a sales exception (C-0910). Team decides before sending.
4. **Escalations show the recommended payout** (capped at declared value) in `approved_amount_inr`, matching how C-0907 was recorded.
5. **C05 says "photos attached" but has no attachment**, so it goes to need_info.
6. **C07 (concealed damage found on unpacking)** is rejected because the POD is clean, per SOP §3.

## Blind back-test (October, code only)
Decision match 21/26, amount match 20/26. The blind rows have no POD and no declared value, so:
C-0905 and C-0912 (team rejected on POD) are approved and flagged "verify POD"; C-0907 and C-0934 are not capped.
The other differences are rules you set: C-0910 (Bluewave sales exception, engine rejects late), C-0920
(under Rs 5,000 = goodwill, team asked for photos), C-0922 (late + no photo = 2 violations = need_info).

## Next steps
- Run the live OpenAI/Gemini cross-check on the blind file and track the agreement rate.
- Add the POD and declared value to the blind file so C-0905, C-0912, C-0907 and C-0934 can be scored fairly.
- Check that the sender domain matches the shipment customer (fraud guard).
- Reply in the customer's language (C09 is Hinglish).
- Track partial-damage amounts against the per-piece value.
