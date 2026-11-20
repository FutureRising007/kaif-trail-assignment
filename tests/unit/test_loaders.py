import tempfile
import unittest
from datetime import date
from pathlib import Path

from claims_engine.loaders import load_emails, load_past_decisions, load_shipments

SHIPMENTS = """shipment_id,customer,delivered_date,pieces_shipped,declared_value_inr,pod_status,pod_remarks
SHP-1003,Zenith Retail,2026-10-29,40,48000,Signed with remarks,37 pieces received
SHP-1007,Sunrise Foods,2026-11-04,50,35000,Signed - received in good condition,
SHP-1009,Desi Bazaar,2026-11-08,25,30000,Signed with remarks,20 received
SHP-1001,Apex Pharma,2026-11-07,30,60000,Signed with remarks,1 box crushed
"""

PAST = """claim_id,shipment_id,customer,claim_type,filed_date,delivered_date,claim_amount_inr,photo_attached,decision,approved_amount_inr,decided_by,notes
C-0931,SHP-0987,Apex Pharma,damage,2026-10-10,2026-10-08,6500,yes,approved,6500,Rahul,"paid 2026-10-20, ref PAY-7781"
"""


class LoaderTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestLoadShipments(LoaderTestBase):
    def setUp(self):
        super().setUp()
        p = self.dir / "shipments.csv"
        p.write_text(SHIPMENTS, encoding="utf-8")
        self.ships = load_shipments(p)

    def test_keyed_by_id_with_types(self):
        s = self.ships["SHP-1003"]
        self.assertEqual(s.customer, "Zenith Retail")
        self.assertEqual(s.delivered_date, date(2026, 10, 29))
        self.assertEqual(s.pieces_shipped, 40)
        self.assertEqual(s.declared_value, 48000)

    def test_pod_clean_flag(self):
        self.assertTrue(self.ships["SHP-1007"].pod_clean)
        self.assertFalse(self.ships["SHP-1003"].pod_clean)

    def test_received_count_from_remarks(self):
        self.assertEqual(self.ships["SHP-1003"].received_count, 37)
        self.assertEqual(self.ships["SHP-1009"].received_count, 20)
        self.assertIsNone(self.ships["SHP-1001"].received_count)  # "1 box crushed" is not a count
        self.assertIsNone(self.ships["SHP-1007"].received_count)


class TestLoadPastDecisions(LoaderTestBase):
    def test_keyed_by_shipment(self):
        p = self.dir / "past.csv"
        p.write_text(PAST, encoding="utf-8")
        past = load_past_decisions(p)
        d = past["SHP-0987"]
        self.assertEqual(d.claim_id, "C-0931")
        self.assertEqual(d.decision, "approved")
        self.assertEqual(d.approved_amount, 6500)
        self.assertIn("PAY-7781", d.notes)


class TestLoadEmails(LoaderTestBase):
    def test_loads_sorted_with_claim_id_from_filename(self):
        for name in ["C02.txt", "C01.txt"]:
            (self.dir / name).write_text(
                "From: a@b.c\nDate: 2026-11-10 09:00\nSubject: x\nAttachments: none\n\nbody", encoding="utf-8")
        emails = load_emails(self.dir)
        self.assertEqual([e.claim_id for e in emails], ["C01", "C02"])


if __name__ == "__main__":
    unittest.main()
