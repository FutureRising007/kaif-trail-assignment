"""Records without POD / declared value (e.g. the October blind file)."""
import unittest

from claims_engine.config import RulesConfig
from claims_engine.models import Shipment
from claims_engine.rules import decide
from claims_engine.violations import detect_violations
from tests.unit.test_rules import item, ship


def unknown_ship(**kw):
    s = ship(**kw)
    return Shipment(s.shipment_id, s.customer, s.delivered_date, 0, 0, "Not available", "",
                    pod_available=False, declared_known=False)


class TestUnknownFacts(unittest.TestCase):
    def setUp(self):
        self.cfg = RulesConfig()

    def run_decide(self, it, s):
        return decide(it, {s.shipment_id: s}, {}, set(), self.cfg)

    def test_defaults_are_known(self):
        s = ship()
        self.assertTrue(s.pod_available and s.declared_known)

    def test_no_pod_violations_when_pod_unavailable(self):
        self.assertEqual(detect_violations(item(), unknown_ship(), self.cfg), [])
        self.assertEqual(detect_violations(item(ctype="shortage", photo=False), unknown_ship(), self.cfg), [])

    def test_no_cap_violation_when_declared_unknown(self):
        vs = detect_violations(item(amount=88000), unknown_ship(), self.cfg)
        self.assertEqual([v.code for v in vs], ["OVER_LIMIT"])

    def test_damage_with_photo_approved_full_amount_and_flagged(self):
        d = self.run_decide(item(amount=30000), unknown_ship())
        self.assertEqual((d.decision, d.approved_amount_inr), ("approve", 30000))
        self.assertTrue(any("POD" in a for a in d.alerts))

    def test_shortage_approved_when_pod_unavailable(self):
        d = self.run_decide(item(ctype="shortage", amount=7000, photo=False), unknown_ship())
        self.assertEqual((d.decision, d.approved_amount_inr), ("approve", 7000))

    def test_escalate_uncapped(self):
        d = self.run_decide(item(amount=88000), unknown_ship())
        self.assertEqual((d.decision, d.approved_amount_inr), ("escalate", 88000))

    def test_missing_photo_still_need_info(self):
        d = self.run_decide(item(amount=12500, photo=False), unknown_ship())
        self.assertEqual(d.decision, "need_info")


if __name__ == "__main__":
    unittest.main()
