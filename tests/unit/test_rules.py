import unittest
from dataclasses import replace
from datetime import date

from claims_engine.config import RulesConfig
from claims_engine.models import ClaimItem, PastDecision, Shipment
from claims_engine.rules import decide

FILED = date(2026, 11, 10)


def ship(sid="SHP-1", customer="Apex Pharma", delivered=date(2026, 11, 7), pieces=30,
         declared=60000, status="Signed with remarks", remarks="1 box crushed"):
    return Shipment(sid, customer, delivered, pieces, declared, status, remarks)


def item(sid="SHP-1", ctype="damage", amount=18000, photo=True, is_claim=True,
         consequential=False, follow_up=False):
    return ClaimItem(claim_id="C99", shipment_id=sid, claim_type=ctype, amount=amount,
                     has_photo=photo, is_claim=is_claim, filed_date=FILED,
                     consequential_loss=consequential, is_follow_up=follow_up, text="")


class RulesBase(unittest.TestCase):
    def setUp(self):
        self.cfg = RulesConfig()

    def run_decide(self, it, shipment=None, past=None, seen=None):
        ships = {} if shipment is None else {shipment.shipment_id: shipment}
        return decide(it, ships, past or {}, seen if seen is not None else set(), self.cfg)


class TestR1NotAClaim(RulesBase):
    def test_non_claim(self):
        d = self.run_decide(item(is_claim=False, ctype=None, amount=None), ship())
        self.assertEqual(d.decision, "not_a_claim")
        self.assertEqual(d.approved_amount_inr, 0)


class TestR2UnknownShipment(RulesBase):
    def test_missing_shipment(self):
        d = self.run_decide(item(sid="SHP-9999"), ship())
        self.assertEqual(d.decision, "need_info")
        self.assertEqual(d.rule, "R2")

    def test_no_shipment_id(self):
        d = self.run_decide(item(sid=None), ship())
        self.assertEqual(d.decision, "need_info")


class TestR3Duplicate(RulesBase):
    def test_past_decision_exists(self):
        past = {"SHP-1": PastDecision("C-0931", "SHP-1", "approved", 6500, "paid 2026-10-20, ref PAY-7781")}
        d = self.run_decide(item(follow_up=True), ship(), past=past)
        self.assertEqual(d.decision, "duplicate")
        self.assertEqual(d.approved_amount_inr, 0)
        self.assertIn("C-0931", d.reason)
        self.assertIn("PAY-7781", d.draft_reply)

    def test_same_shipment_twice_in_batch(self):
        d = self.run_decide(item(), ship(), seen={"SHP-1"})
        self.assertEqual(d.decision, "duplicate")


class TestR4TimeWindow(RulesBase):
    def test_late_default_window(self):
        d = self.run_decide(item(), ship(delivered=date(2026, 11, 2)))  # 8 days
        self.assertEqual((d.decision, d.rule), ("reject", "R4"))

    def test_exactly_seven_days_ok(self):
        d = self.run_decide(item(), ship(delivered=date(2026, 11, 3)))
        self.assertEqual(d.decision, "approve")

    def test_late_small_claim_still_rejected(self):  # precedent C-0922
        d = self.run_decide(item(amount=2000, photo=False), ship(delivered=date(2026, 11, 2)))
        self.assertEqual(d.decision, "reject")

    def test_key_account_extended_window(self):
        s = ship(customer="Zenith Retail", delivered=date(2026, 10, 29))  # 12 days
        d = self.run_decide(item(), s)
        self.assertEqual(d.decision, "approve")

    def test_key_account_beyond_extended_window(self):  # precedent C-0914 (17 days)
        s = ship(customer="Zenith Retail", delivered=date(2026, 10, 24))
        d = self.run_decide(item(), s)
        self.assertEqual(d.decision, "reject")


class TestR5Goodwill(RulesBase):
    def test_small_claim_without_photo_approved_goodwill(self):
        d = self.run_decide(item(amount=3200, photo=False), ship())
        self.assertEqual((d.decision, d.approved_amount_inr), ("approve", 3200))
        self.assertIn("GoodWill & Passes", d.reason)

    def test_threshold_is_strictly_below_5000(self):
        d = self.run_decide(item(amount=5000, photo=False), ship())
        self.assertEqual(d.decision, "need_info")


class TestR6R7PodChecks(RulesBase):
    def test_damage_with_clean_pod_rejected(self):
        s = ship(status="Signed - received in good condition", remarks="")
        d = self.run_decide(item(amount=12000), s)
        self.assertEqual((d.decision, d.rule), ("reject", "R6"))

    def test_shortage_with_full_count_rejected(self):
        s = ship(pieces=12, status="Signed - received in good condition", remarks="12 pieces received")
        d = self.run_decide(item(ctype="shortage", amount=30000, photo=False), s)
        self.assertEqual((d.decision, d.rule), ("reject", "R7"))


class TestR8R9Shortage(RulesBase):
    def test_shortage_confirmed_by_pod_approved_without_photo(self):
        s = ship(pieces=25, declared=30000, remarks="20 received")
        d = self.run_decide(item(ctype="shortage", amount=7500, photo=False), s)
        self.assertEqual((d.decision, d.approved_amount_inr), ("approve", 7500))

    def test_shortage_without_pod_count_needs_info(self):
        d = self.run_decide(item(ctype="shortage", amount=7500, photo=False), ship(remarks="outer carton damaged"))
        self.assertEqual((d.decision, d.rule), ("need_info", "R9"))


class TestR10Photos(RulesBase):
    def test_damage_without_photo_needs_info(self):
        d = self.run_decide(item(amount=14500, photo=False), ship())
        self.assertEqual((d.decision, d.rule), ("need_info", "R10"))
        self.assertIn("photo", d.draft_reply.lower())


class TestR11R12CapAndEscalation(RulesBase):
    def test_capped_at_declared_value(self):
        d = self.run_decide(item(amount=30000), ship(declared=26000))
        self.assertEqual((d.decision, d.approved_amount_inr), ("approve", 26000))
        self.assertIn("declared value", d.reason)

    def test_above_manager_limit_escalated(self):
        d = self.run_decide(item(amount=58000), ship(declared=120000))
        self.assertEqual((d.decision, d.approved_amount_inr), ("escalate", 58000))
        self.assertTrue(any("Meera" in a for a in d.alerts))

    def test_cap_then_escalate(self):  # precedent C-0907
        d = self.run_decide(item(amount=95000, consequential=True), ship(declared=72000))
        self.assertEqual((d.decision, d.approved_amount_inr), ("escalate", 72000))
        self.assertTrue(any("consequential" in a.lower() for a in d.alerts))

    def test_exactly_50000_not_escalated(self):
        d = self.run_decide(item(amount=50000), ship(declared=60000))
        self.assertEqual(d.decision, "approve")


class TestTeamAlerts(RulesBase):
    def test_bluewave_follows_sop_but_alerts_team(self):
        s = ship(customer="Bluewave Electronics")
        d = self.run_decide(item(amount=22000), s)
        self.assertEqual(d.decision, "approve")
        self.assertTrue(any("Bluewave" in a for a in d.alerts))
        self.assertIn("TEAM ALERT", d.reason)

    def test_bluewave_late_is_still_rejected_but_alerted(self):
        s = ship(customer="Bluewave Electronics", delivered=date(2026, 10, 30))
        d = self.run_decide(item(amount=22000), s)
        self.assertEqual(d.decision, "reject")
        self.assertTrue(d.alerts)

    def test_zenith_alerted(self):
        d = self.run_decide(item(), ship(customer="Zenith Retail"))
        self.assertTrue(any("Zenith" in a for a in d.alerts))

    def test_regular_customer_no_alert(self):
        d = self.run_decide(item(), ship())
        self.assertEqual(d.alerts, [])


class TestApproveDefault(RulesBase):
    def test_plain_valid_damage(self):
        d = self.run_decide(item(), ship())
        self.assertEqual((d.decision, d.approved_amount_inr, d.rule), ("approve", 18000, "R13"))
        self.assertTrue(d.draft_reply)

    def test_decision_values_are_from_allowed_set(self):
        allowed = {"approve", "reject", "need_info", "escalate", "duplicate", "not_a_claim"}
        for it in [item(), item(is_claim=False), item(photo=False), item(amount=90000)]:
            self.assertIn(self.run_decide(it, ship()).decision, allowed)

    def test_missing_amount_needs_info(self):
        d = self.run_decide(item(amount=None), ship())
        self.assertEqual(d.decision, "need_info")


if __name__ == "__main__":
    unittest.main()
