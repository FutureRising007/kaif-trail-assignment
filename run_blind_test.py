"""Back-test the engine on the blind October file and score it against the real decisions.

python run_blind_test.py [--blind CSV] [--answers CSV] [--out CSV] [--llm openai,gemini] [--no-llm]
"""
import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from claims_engine.blind import run_blind
from claims_engine.cli_common import add_llm_args, load_dotenv, make_reviewer
from claims_engine.config import RulesConfig

ROOT = Path(__file__).resolve().parent


def main() -> None:
    p = argparse.ArgumentParser(description="Blind back-test against October decisions")
    p.add_argument("--blind", type=Path,
                   default=ROOT / "tests" / "blind" / "past_decisions_oct-test - past_decisions_oct.csv")
    p.add_argument("--answers", type=Path, default=ROOT / "data" / "past_decisions_oct.csv")
    p.add_argument("--sop", type=Path, default=ROOT / "data" / "claims_sop.md")
    p.add_argument("--out", type=Path, default=ROOT / "output" / "blind_test_results.csv")
    add_llm_args(p)
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    load_dotenv(ROOT / ".env")

    cfg = RulesConfig()
    reviewer, llm_status = make_reviewer(a.sop, cfg, a.llm, not a.no_llm)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    rows, s = run_blind(a.blind, a.out, answer_csv=a.answers if a.answers.exists() else None,
                        reviewer=reviewer, cfg=cfg)

    print(f"LLM review: {llm_status}")
    print(f"Decided {s['claims']} claims -> {a.out}")
    for status, n in sorted(Counter(r["approval_status"] for r in rows).items()):
        print(f"  {status:<26}{n}")
    print(f"LLM consulted {s['llm_consulted']}: agree {s['llm_agree']}, disagree {s['llm_disagree']}, "
          f"unavailable {s['llm_unavailable']}")
    if "decision_matches" in s:
        print(f"Decision match vs October team: {s['decision_matches']}/{s['claims']}")
        print(f"Amount match vs October team:   {s['amount_matches']}/{s['claims']}")
        for r in rows:
            if r["decision_match"] == "no" or r["amount_match"] == "no":
                print(f"  {r['claim_id']}: engine {r['decision']} {r['approved_amount_inr']} | "
                      f"team {r['actual_decision']} {r['actual_amount_inr']}")


if __name__ == "__main__":
    main()
