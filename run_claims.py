"""CLI: python run_claims.py [--emails DIR] [--shipments CSV] [--past CSV] [--sop MD] [--out DIR]
                            [--llm openai,gemini] [--no-llm]"""
import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from claims_engine.cli_common import add_llm_args, load_dotenv, make_reviewer
from claims_engine.config import RulesConfig
from claims_engine.pipeline import run

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def main() -> None:
    p = argparse.ArgumentParser(description="RouteMax daily claims triage")
    p.add_argument("--emails", type=Path, default=DATA / "claim_emails")
    p.add_argument("--shipments", type=Path, default=DATA / "shipments.csv")
    p.add_argument("--past", type=Path, default=DATA / "past_decisions_oct.csv")
    p.add_argument("--sop", type=Path, default=DATA / "claims_sop.md")
    p.add_argument("--out", type=Path, default=ROOT / "output")
    add_llm_args(p)
    a = p.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    load_dotenv(ROOT / ".env")

    cfg = RulesConfig()
    reviewer, llm_status = make_reviewer(a.sop, cfg, a.llm, not a.no_llm)
    decisions = run(a.emails, a.shipments, a.past, a.out, cfg=cfg, reviewer=reviewer)
    counts = Counter(d.decision for d in decisions)
    print(f"LLM review: {llm_status}")
    print(f"Processed {len(decisions)} claims -> {a.out / 'results.csv'}")
    for k, v in sorted(counts.items()):
        print(f"  {k:<12}{v}")
    print(f"Team alerts: {sum(len(d.alerts) for d in decisions)} -> {a.out / 'team_alerts.csv'}")
    print(f"Code vs LLM audit -> {a.out / 'llm_audit.csv'}")


if __name__ == "__main__":
    main()
