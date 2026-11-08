import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import tokens  # noqa: E402


def asst(mid, model, inp, out, cr=0, cc=0):
    return json.dumps({"type": "assistant", "requestId": "r" + mid, "timestamp": "2026-10-26T21:00:00Z",
                       "message": {"id": mid, "role": "assistant", "model": model, "stop_reason": "end_turn",
                                   "content": [{"type": "text", "text": "x"}],
                                   "usage": {"input_tokens": inp, "output_tokens": out,
                                             "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc}}})


class PricesTest(unittest.TestCase):
    def setUp(self):
        os.environ["SJCK_FX_OFFLINE"] = "1"
        self.addCleanup(os.environ.pop, "SJCK_FX_OFFLINE", None)
        self.root = tempfile.mkdtemp(prefix="sjck-prices-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, ".sjck"))
        self._json("state.json", {"status": "running", "nodes": [{"id": "T01", "status": "running", "agent_id": "a"}]})

    def _json(self, name, data):
        with open(os.path.join(self.root, ".sjck", name), "w") as f:
            json.dump(data, f)

    def _src(self, name, label, kind, lines):
        p = os.path.join(self.root, name)
        with open(p, "w") as f:
            f.write("\n".join(lines) + "\n")
        tokens.add_source(self.root, p, label, kind)

    def test_defaults_and_override_change_cost(self):
        p = tokens.load_prices(self.root)
        self.assertEqual(p["multipliers"]["cache_read"], 0.1)
        self.assertIn("sonnet", p["models"])
        use = {"input": 1000000, "output": 0, "cache_read": 0, "cache_creation": 0}
        base = tokens.estimate_usd(p, "claude-sonnet-4", use)
        self.assertAlmostEqual(base, 3.0)
        self._json("prices.json", {"models": {"sonnet": {"input_per_mtok": 6.0}}})
        p2 = tokens.load_prices(self.root)
        self.assertAlmostEqual(tokens.estimate_usd(p2, "claude-sonnet-4", use), 6.0)
        self.assertIn("opus", p2["models"])  # merge per chiave: gli altri default restano
        self.assertEqual(p2["multipliers"]["output"], 5.0)

    def test_override_reaches_tokens_json(self):
        self._src("m.jsonl", "ORCH", "main", [asst("a", "claude-sonnet-4", 1000000, 0)])
        self.assertAlmostEqual(tokens.build(self.root)["cost"]["usd"], 3.0)
        self._json("prices.json", {"models": {"sonnet": {"input_per_mtok": 9.0}}})
        self.assertAlmostEqual(tokens.build(self.root)["cost"]["usd"], 9.0)

    def test_cache_multipliers(self):
        p = tokens.load_prices(self.root)
        one = lambda k: tokens.estimate_usd(p, "claude-sonnet-4", dict({x: 0 for x in tokens.KEYS}, **{k: 1000000}))
        self.assertLess(one("cache_read"), one("input"))
        self.assertGreater(one("cache_creation"), one("input"))
        self.assertGreater(one("output"), one("input"))

    def test_unknown_model_uses_default_and_no_prices_gives_none(self):
        p = tokens.load_prices(self.root)
        use = {"input": 1000000}
        self.assertAlmostEqual(tokens.estimate_usd(p, "mystery-model", use), 3.0)
        self.assertIsNone(tokens.estimate_usd({"models": {}}, "mystery-model", use))

    def test_real_cost_vs_estimated(self):
        self._src("m.jsonl", "ORCH", "main", [
            asst("a", "claude-sonnet-4", 1000000, 0),
            json.dumps({"type": "cost-state", "sessionId": "S", "totalCostUSD": 7.5, "modelUsage": {}})])
        d = tokens.build(self.root)
        self.assertEqual(d["cost"]["usd"], 7.5)
        self.assertIs(d["cost"]["estimated"], False)
        self.assertIs(d["by_node"]["ORCH"]["estimated"], False)
        shutil.rmtree(self.root)
        self.setUp()
        self._src("m.jsonl", "ORCH", "main", [asst("a", "claude-sonnet-4", 1000000, 0)])
        d = tokens.build(self.root)
        self.assertAlmostEqual(d["cost"]["usd"], 3.0)
        self.assertIs(d["cost"]["estimated"], True)
        self.assertIs(d["by_node"]["ORCH"]["estimated"], True)

    def test_report_has_node_agent_and_run_cost(self):
        self._src("m.jsonl", "ORCH", "main", [asst("a", "claude-opus-4", 1000000, 0)])
        self._src("sub.jsonl", "T01", "agent", [asst("b", "claude-sonnet-4", 0, 1000000)])
        tokens.refresh(self.root)
        with open(os.path.join(self.root, ".sjck", "token-report.json")) as f:
            c = json.load(f)["cost"]
        self.assertAlmostEqual(c["usd"], 5.0 + 15.0)
        self.assertAlmostEqual(c["by_node"]["ORCH"]["usd"], 5.0)
        self.assertAlmostEqual(c["by_node"]["T01"]["usd"], 15.0)
        self.assertAlmostEqual(c["by_agent"]["sub"]["usd"], 15.0)
        self.assertEqual(c["by_agent"]["sub"]["node"], "T01")
        self.assertIs(c["by_node"]["T01"]["estimated"], True)
        self.assertIs(c["estimated"], True)

    def test_by_node_models_are_dicts(self):
        self._src("m.jsonl", "T01", "agent", [asst("a", "claude-sonnet-4", 10, 5, cr=100, cc=20),
                                              asst("b", "claude-opus-4", 1, 1)])
        d = tokens.build(self.root)
        m = d["by_node"]["T01"]["models"]
        self.assertEqual(m["claude-sonnet-4"], {"input": 10, "output": 5, "cache_read": 100, "cache_creation": 20, "total": 135})
        self.assertEqual(m["claude-opus-4"]["total"], 2)

    def test_old_integer_models_form_still_readable(self):
        old = {"by_node": {"T01": {"input": 50000, "output": 0, "cache_read": 0, "cache_creation": 0, "total": 50000,
                                   "turns": 1, "categories": {}, "models": {"claude-opus-4": 50000}}}}
        state = {"nodes": [{"id": "T01", "status": "validated", "attempts": 0, "files": ["a"]}]}
        rep = tokens.analyze(old, state)
        self.assertTrue(any(i["kind"] == "model" for i in rep["insights"]))
        self.assertEqual(tokens._mtotal(50000), 50000)
        self.assertEqual(tokens._mtotal({"total": 7}), 7)


if __name__ == "__main__":
    unittest.main()
