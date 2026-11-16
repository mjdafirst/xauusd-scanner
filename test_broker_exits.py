import unittest
from unittest.mock import patch
import broker_exits as b


class BrokerExitTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.multiple(b.config, OANDA_API_TOKEN="fake", OANDA_ACCOUNT_ID="test-account", OANDA_ENVIRONMENT="practice")
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.state = {}
        b.register_fill({"orderFillTransaction": {"type": "ORDER_FILL", "tradeOpened": {"tradeID": "12"}}}, {"direction": "SHORT", "model": "Model 4"}, self.state)
        self.trade = {"id": "12", "instrument": "XAU_USD", "state": "CLOSED", "closingTransactionIDs": ["19", "20"], "realizedPL": "5", "averageClosePrice": "10"}
        self.tx = {"id": "20", "type": "ORDER_FILL", "reason": "TAKE_PROFIT_ORDER", "tradesClosed": [{"tradeID": "12"}], "price": "10"}

    def fetch(self, path):
        if path == "trades/12": return {"trade": self.trade}
        if path == "transactions/20": return {"transaction": self.tx}
        raise AssertionError(path)

    def test_tp_and_deduplication(self):
        sent = []
        b.poll(self.state, lambda text: sent.append(text) or True, self.fetch)
        b.poll(self.state, lambda text: sent.append(text) or True, self.fetch)
        self.assertEqual(len(sent), 1)
        self.assertIn("TAKE PROFIT", sent[0])

    def test_sl(self):
        self.tx["reason"] = "STOP_LOSS_ORDER"
        sent = []
        b.poll(self.state, lambda text: sent.append(text) or True, self.fetch)
        self.assertIn("STOP LOSS", sent[0])

    def test_other_close_not_tp(self):
        self.tx["reason"] = "MARKET_ORDER_TRADE_CLOSE"
        sent = []
        b.poll(self.state, lambda text: sent.append(text) or True, self.fetch)
        self.assertIn("OTHER CLOSE", sent[0])

    def test_partial_trade_waits(self):
        self.trade["state"] = "OPEN"
        b.poll(self.state, lambda text: self.fail("premature send"), self.fetch)
        self.assertEqual(len(self.state["broker_trades"]), 1)

    def test_telegram_failure_retries(self):
        b.poll(self.state, lambda text: False, self.fetch)
        self.assertEqual(len(self.state["broker_trades"]), 1)
        b.poll(self.state, lambda text: True, lambda path: self.fail("pending delivery should not refetch"))
        self.assertFalse(self.state["broker_trades"])

    def test_api_failure_keeps_record(self):
        def fail(path): raise RuntimeError("offline")
        b.poll(self.state, lambda text: self.fail("no broker proof"), fail)
        self.assertEqual(len(self.state["broker_trades"]), 1)

    def test_account_change_skips_record(self):
        with patch.object(b.config, "OANDA_ACCOUNT_ID", "another-account"):
            b.poll(self.state, lambda text: self.fail("wrong account"), lambda path: self.fail("wrong account fetch"))
        self.assertEqual(len(self.state["broker_trades"]), 1)

    def test_wrong_trade_transaction_kept(self):
        self.tx["tradesClosed"] = [{"tradeID": "99"}]
        b.poll(self.state, lambda text: self.fail("wrong trade"), self.fetch)
        self.assertEqual(len(self.state["broker_trades"]), 1)

    def test_no_fill_not_registered(self):
        state = {}
        b.register_fill({"orderCancelTransaction": {}}, {}, state)
        self.assertFalse(state)


if __name__ == "__main__":
    unittest.main()
