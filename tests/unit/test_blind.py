import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from claims_engine.blind import PAST_VOCAB, row_to_case, run_blind

HEADER = ("claim_id,shipment_id,customer,claim_type,filed_date,delivered_date,claim_amount_inr,"
          "photo_attached,decision,approved_amount_inr,decided_by,notes\n")
BLIND = HEADER + (
    "C-1,SHP-1,Kirana Mart,damage,2026-10-02,2026-09-30,2400,no,,,,\n"
    "C-2,SHP-2,Nova Textiles,damage,2026-10-03,2026-09-24,8000,yes,,,,\n"
    "C-3,SHP-3,Orbit Auto Parts,damage,2026-10-06,2026-10-02,88000,yes,,,,\n"
)
ANSWERS = HEADER + (
    "C-1,SHP-1,Kirana Mart,damage,2026-10-02,2026-09-30,2400,no,approved,2400,Rahul,\n"
    "C-2,SHP-2,Nova Textiles,damage,2026-10-03,2026-09-24,8000,yes,rejected,0,Rahul,late\n"
    "C-3,SHP-3,Orbit Auto Parts,damage,2026-10-06,2026-10-02,88000,yes,escalated,64000,Meera,capped\n"
)


class TestRowToCase(unittest.TestCase):
    def test_builds_item_and_unknown_shipment(self):
        row = next(csv.DictReader(BLIND.splitlines()))
        it, shp, text, attachments = row_to_case(row)
        self.assertEqual((it.claim_id, it.shipment_id, it.claim_type, it.amount),
                         ("C-1", "SHP-1", "damage", 2400))
        self.assertEqual(it.filed_date, date(2026, 10, 2))
        self.assertFalse(it.has_photo)
        self.assertEqual(attachments, [])
        self.assertEqual(shp.delivered_date, date(2026, 9, 30))
        self.assertFalse(shp.pod_available)
        self.assertFalse(shp.declared_known)
        self.assertIn("Rs 2,400", text)

    def test_photo_yes_gives_attachment(self):
        rows = list(csv.DictReader(BLIND.splitlines()))
        self.assertTrue(row_to_case(rows[1])[0].has_photo)
        self.assertEqual(len(row_to_case(rows[1])[3]), 1)


class TestVocab(unittest.TestCase):
    def test_maps_to_past_file_wording(self):
        self.assertEqual(PAST_VOCAB["approve"], "approved")
        self.assertEqual(PAST_VOCAB["reject"], "rejected")
        self.assertEqual(PAST_VOCAB["escalate"], "escalated")
        self.assertEqual(PAST_VOCAB["need_info"], "need_info")


class TestRunBlind(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "blind.csv").write_text(BLIND, encoding="utf-8")
        (d / "answers.csv").write_text(ANSWERS, encoding="utf-8")
        self.out = d / "out.csv"
        self.rows, self.summary = run_blind(d / "blind.csv", self.out, answer_csv=d / "answers.csv")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fills_decision_columns(self):
        got = [(r["decision"], r["approved_amount_inr"]) for r in self.rows]
        self.assertEqual(got, [("approved", 2400), ("rejected", 0), ("escalated", 88000)])
        self.assertTrue(all(r["decided_by"].startswith("auto") for r in self.rows))
        self.assertTrue(all(r["notes"] for r in self.rows))

    def test_scores_against_answers(self):
        self.assertEqual(self.summary["claims"], 3)
        self.assertEqual(self.summary["decision_matches"], 3)
        self.assertEqual(self.summary["amount_matches"], 2)  # 88,000 vs capped 64,000
        self.assertEqual(self.rows[2]["amount_match"], "no")

    def test_written_file_keeps_original_columns_first(self):
        with open(self.out, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        self.assertEqual(header[:12], HEADER.strip().split(","))
        self.assertIn("approval_status", header)

    def test_approval_status_column(self):
        self.assertEqual([r["approval_status"] for r in self.rows],
                         ["APPROVED", "NOT APPROVED", "PENDING MANAGER APPROVAL"])

    def test_without_answers_no_scoring(self):
        rows, summary = run_blind(Path(self.tmp.name) / "blind.csv", self.out)
        self.assertNotIn("decision_matches", summary)
        self.assertEqual(rows[0]["decision"], "approved")


if __name__ == "__main__":
    unittest.main()
