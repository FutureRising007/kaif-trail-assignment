"""End-to-end: real input files in data/ -> results.csv + team_alerts.csv."""
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from claims_engine.llm_reviewer import LLMVerdict
from claims_engine.pipeline import run

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

# (claim_id, shipment_id) -> (decision, approved_amount_inr)
EXPECTED = {
    ("C01", "SHP-1001"): ("approve", 18000),     # in window, photos, POD remark
    ("C02", "SHP-1002"): ("reject", 0),          # 11 days late (Bluewave -> alert)
    ("C03", "SHP-1003"): ("approve", 9000),      # Zenith 15-day window, POD 37/40
    ("C04", "SHP-1004"): ("approve", 3200),      # < 5k goodwill, no photo
    ("C05", "SHP-1005"): ("need_info", 0),       # says photos attached, none attached
    ("C06", "SHP-1006"): ("need_info", 0),       # 2 violations: §5 over declared + §6 over 50k
    ("C07", "SHP-1007"): ("reject", 0),          # clean POD
    ("C08", "SHP-0987"): ("duplicate", 0),       # already paid PAY-7781
    ("C09", "SHP-1009"): ("approve", 7500),      # Hinglish shortage, POD 20/25
    ("C10", "SHP-1010"): ("approve", 4000),      # SHP-1O10 typo normalised, < 5k
    ("C11", "SHP-1011"): ("reject", 0),          # POD full count (Bluewave -> alert)
    ("C12", "SHP-1012"): ("need_info", 0),       # 2 violations: §1 late + §2 no photo
    ("C13", "SHP-1013"): ("escalate", 58000),    # > 50k, Zenith
    ("C14", "SHP-1014"): ("approve", 6000),      # multi-claim email, part 1
    ("C14", "SHP-1015"): ("approve", 4500),      # multi-claim email, part 2, goodwill
    ("C15", "SHP-1016"): ("not_a_claim", 0),     # invoice/POD request
}

COLUMNS = ["claim_id", "shipment_id", "decision", "approved_amount_inr", "reason", "draft_reply"]


class TestPipelineEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.decisions = run(DATA / "claim_emails", DATA / "shipments.csv",
                            DATA / "past_decisions_oct.csv", cls.out)
        with open(cls.out / "results.csv", newline="", encoding="utf-8-sig") as f:
            cls.reader_fields = csv.DictReader(f).fieldnames
        with open(cls.out / "results.csv", newline="", encoding="utf-8-sig") as f:
            cls.rows = list(csv.DictReader(f))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exact_columns(self):
        self.assertEqual(self.reader_fields, COLUMNS)

    def test_one_row_per_claim(self):
        self.assertEqual(len(self.rows), len(EXPECTED))

    def test_every_decision_matches_expected(self):
        got = {(r["claim_id"], r["shipment_id"]): (r["decision"], int(r["approved_amount_inr"]))
               for r in self.rows}
        for key, want in EXPECTED.items():
            with self.subTest(claim=key):
                self.assertEqual(got.get(key), want)

    def test_multi_claim_email_shares_claim_id(self):
        self.assertEqual(sum(1 for r in self.rows if r["claim_id"] == "C14"), 2)

    def test_every_row_has_reason_and_reply(self):
        for r in self.rows:
            with self.subTest(claim=r["claim_id"]):
                self.assertTrue(r["reason"].strip())
                self.assertTrue(r["draft_reply"].strip())

    def test_goodwill_tag_on_small_approvals(self):
        for r in self.rows:
            if r["decision"] == "approve" and int(r["approved_amount_inr"]) < 5000:
                self.assertIn("GoodWill & Passes", r["reason"])

    def test_team_alerts_file(self):
        with open(self.out / "team_alerts.csv", newline="", encoding="utf-8-sig") as f:
            alerts = list(csv.DictReader(f))
        flagged = {a["shipment_id"] for a in alerts}
        # Bluewave (both), Zenith (both), escalations
        for sid in ["SHP-1002", "SHP-1011", "SHP-1003", "SHP-1013", "SHP-1006"]:
            self.assertIn(sid, flagged)

    def test_multi_violation_rows_cite_sop(self):
        rows = {r["claim_id"]: r for r in self.rows}
        self.assertIn("SOP §5 Maximum payout", rows["C06"]["reason"])
        self.assertIn("SOP §6 Approval limit", rows["C06"]["reason"])
        self.assertIn("SOP §1 Time limit", rows["C12"]["reason"])
        self.assertIn("SOP §2 Evidence", rows["C12"]["reason"])

    def test_audit_file_paths(self):
        with open(self.out / "llm_audit.csv", newline="", encoding="utf-8-sig") as f:
            audit = {(a["claim_id"], a["shipment_id"]): a["path"] for a in csv.DictReader(f)}
        self.assertEqual(len(audit), len(EXPECTED))
        self.assertEqual(audit[("C01", "SHP-1001")], "no_violation")
        self.assertEqual(audit[("C08", "SHP-0987")], "precheck")
        self.assertEqual(audit[("C13", "SHP-1013")], "single_violation")
        self.assertEqual(audit[("C06", "SHP-1006")], "multi_violation")

    def test_cli_runs(self):
        with tempfile.TemporaryDirectory() as d:
            res = subprocess.run([sys.executable, str(ROOT / "run_claims.py"), "--out", d, "--no-llm"],
                                 capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue((Path(d) / "results.csv").exists())
            self.assertTrue((Path(d) / "llm_audit.csv").exists())


class AlwaysApproveLLM:
    """A badly behaved LLM: approves everything with a fake reference."""

    def __init__(self):
        self.calls = 0

    def review(self, case):
        self.calls += 1
        return LLMVerdict("approve", [], "looks fine")


class TestCodeWinsOverLLM(unittest.TestCase):
    def test_disagreeing_llm_changes_no_decision(self):
        llm = AlwaysApproveLLM()
        with tempfile.TemporaryDirectory() as d:
            decisions = run(DATA / "claim_emails", DATA / "shipments.csv",
                            DATA / "past_decisions_oct.csv", Path(d), reviewer=llm)
            got = {(x.claim_id, x.shipment_id): (x.decision, x.approved_amount_inr) for x in decisions}
            self.assertEqual(got, EXPECTED)
            # LLM is only consulted for violation cases (C02 C04 C05 C06 C07 C11 C12 C13 C14/1015)
            self.assertEqual(llm.calls, 9)
            with open(Path(d) / "llm_audit.csv", newline="", encoding="utf-8-sig") as f:
                disagreements = [a for a in csv.DictReader(f) if a["agreement"] == "disagree"]
            # approves are agreements (C04, C14/1015); every other consulted claim is a disagreement
            self.assertEqual(len(disagreements), 7)
            flagged = [x for x in decisions if any("code decision kept" in a for a in x.alerts)]
            self.assertEqual(len(flagged), 7)


if __name__ == "__main__":
    unittest.main()
