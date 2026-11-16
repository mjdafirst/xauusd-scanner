import unittest
from order_feedback import format_order_result


class OrderFeedbackTests(unittest.TestCase):
    def message(self, result):
        return format_order_result(result, "SHORT", "Model 4", "101-004-1234567-001", "practice")

    def test_verified_fill(self):
        text = self.message({"orderFillTransaction": {"type": "ORDER_FILL", "id": "42", "price": "3874.5", "units": "-10", "tradeOpened": {"tradeID": "43"}}})
        self.assertIn("FILL CONFIRMED", text)
        self.assertIn("Actual fill price: 3874.5", text)
        self.assertIn("Opened trade ID: 43", text)
        self.assertNotIn("1234567", text)

    def test_cancelled(self):
        self.assertIn("CANCELLED", self.message({"orderCancelTransaction": {"reason": "MARKET_HALTED"}}))

    def test_rejected(self):
        self.assertIn("REJECTED", self.message({"orderRejectTransaction": {"rejectReason": "INSUFFICIENT_MARGIN"}}))

    def test_acceptance_is_not_fill(self):
        self.assertIn("FILL NOT CONFIRMED", self.message({"orderCreateTransaction": {"id": "1"}}))

    def test_network_failure_is_uncertain(self):
        text = self.message(None)
        self.assertIn("FILL NOT CONFIRMED", text)
        self.assertIn("may have executed", text)

    def test_malformed_fill(self):
        for fill in (None, {}, {"type": "ORDER_FILL", "id": "1"}, {"type": "ORDER_CREATE", "id": "1", "price": "1", "units": "1"}):
            self.assertIn("FILL NOT CONFIRMED", self.message({"orderFillTransaction": fill}))

    def test_netting_is_not_new_trade(self):
        text = self.message({"orderFillTransaction": {"type": "ORDER_FILL", "id": "42", "price": "3874.5", "units": "-10", "tradesClosed": [{"tradeID": "2"}]}})
        self.assertIn("No new trade ID", text)


if __name__ == "__main__":
    unittest.main()
