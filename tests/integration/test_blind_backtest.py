"""Back-test on the October blind file, scored against data/past_decisions_oct.csv."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from claims_engine.blind import run_blind

ROOT = Path(__file__).resolve().parents[2]
BLIND = ROOT / "tests" / "blind" / "past_decisions_oct-test - past_decisions_oct.csv"
ANSWERS = ROOT / "data" / "past_decisions_oct.csv"

# claim_id -> (engine decision, amount). Rows marked * differ from October's team.
EXPECTED = {
    "C-0901": ("approved", 2400), "C-0902": ("approved", 15000), "C-0903": ("rejected", 0),
    "C-0904": ("approved", 6000),
    "C-0905": ("approved", 9000),      # * team rejected: POD clean (POD not in blind file)
    "C-0906": ("approved", 3100),
    "C-0907": ("escalated", 88000),    # amount * team capped at declared 64,000 (not in blind file)
    "C-0908": ("need_info", 0), "C-0909": ("approved", 4800),
    "C-0910": ("rejected", 0),         # * team approved late claim as a sales exception
    "C-0911": ("approved", 14000),
    "C-0912": ("approved", 5000),      # * team rejected: POD full count (POD not in blind file)
    "C-0913": ("approved", 1900), "C-0914": ("rejected", 0), "C-0915": ("escalated", 65000),
    "C-0916": ("approved", 4500), "C-0917": ("rejected", 0), "C-0918": ("approved", 3800),
    "C-0919": ("need_info", 0),
    "C-0920": ("approved", 4200),      # * team asked for photos; rule: under Rs 5,000 is goodwill
    "C-0921": ("escalated", 52000),
    "C-0922": ("need_info", 0),        # * team rejected; rule: late + no photo = 2 violations
    "C-0931": ("approved", 6500), "C-0932": ("approved", 7000), "C-0933": ("approved", 18000),
    "C-0934": ("approved", 30000),     # amount * team capped at declared 26,000
}


class TestBlindBacktest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "scored.csv"
        cls.rows, cls.summary = run_blind(BLIND, cls.out, answer_csv=ANSWERS)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_blind_file_has_no_answers(self):
        import csv
        with open(BLIND, newline="", encoding="utf-8-sig") as f:
            self.assertTrue(all(not r["decision"] for r in csv.DictReader(f)))

    def test_every_claim_decided_as_expected(self):
        got = {r["claim_id"]: (r["decision"], r["approved_amount_inr"]) for r in self.rows}
        for cid, want in EXPECTED.items():
            with self.subTest(claim=cid):
                self.assertEqual(got[cid], want)

    def test_score(self):
        self.assertEqual(self.summary["claims"], 26)
        self.assertEqual(self.summary["decision_matches"], 21)
        self.assertEqual(self.summary["amount_matches"], 20)  # off: 0905 0907 0910 0912 0920 0934

    def test_approval_status_marked_on_every_row(self):
        allowed = {"APPROVED", "NOT APPROVED", "PENDING MANAGER APPROVAL", "ON HOLD - INFO REQUESTED"}
        self.assertTrue(all(r["approval_status"] in allowed for r in self.rows))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.csv"
            res = subprocess.run([sys.executable, str(ROOT / "run_blind_test.py"), "--out", str(out), "--no-llm"],
                                 capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("21/26", res.stdout)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
