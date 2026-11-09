"""P1 — costo per AGENTE (un transcript) oltre che per nodo, modello e run.

I prezzi e la loro risoluzione sono testati in test_cost.py (config.py): qui si
verifica quello che tokens.py aggiunge sopra, cioe' `by_agent`, la forma per
modello di `by_node[].models` e il blocco `cost` di token-report.json.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import tokens  # noqa: E402

M = 1e6


def asst(mid, model, inp, out, cr=0, cc=0):
    return json.dumps({"type": "assistant", "requestId": "r" + mid, "timestamp": "2026-11-09T21:00:00Z",
                       "message": {"id": mid, "role": "assistant", "model": model, "stop_reason": "end_turn",
                                   "content": [{"type": "text", "text": "x"}],
                                   "usage": {"input_tokens": inp, "output_tokens": out,
                                             "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc}}})


class PricesTest(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))
        os.environ["SJCK_FX_OFFLINE"] = "1"
        home = tempfile.mkdtemp(prefix="sjck-home-")
        self.addCleanup(shutil.rmtree, home, True)
        os.environ["HOME"] = home          # config.py legge ~/.sjck/prices.json
        os.environ.pop("SJCK_PRICES", None)
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

    def test_override_reaches_tokens_json(self):
        self._src("m.jsonl", "ORCH", "main", [asst("a", "claude-sonnet-5-5", 1000000, 0)])
        self.assertAlmostEqual(tokens.build(self.root)["cost"]["usd"], 2.0)
        self._json("prices.json", {"models": {"claude-sonnet-5-5": {"input": 9.0, "output": 10.0}}})
        self.assertAlmostEqual(tokens.build(self.root)["cost"]["usd"], 9.0)

    def test_report_has_node_agent_and_run_cost(self):
        self._src("m.jsonl", "ORCH", "main", [asst("a", "claude-opus-5-5", 1000000, 0)])
        self._src("sub.jsonl", "T01", "agent", [asst("b", "claude-sonnet-5-5", 0, 0, cc=1000000)])
        tokens.refresh(self.root)
        with open(os.path.join(self.root, ".sjck", "token-report.json")) as f:
            c = json.load(f)["cost"]
        self.assertAlmostEqual(c["usd"], 4.0 + 2.5)          # opus input + sonnet cache write
        self.assertAlmostEqual(c["by_node"]["ORCH"]["usd"], 4.0)
        self.assertAlmostEqual(c["by_node"]["T01"]["usd"], 2.5)
        self.assertAlmostEqual(c["by_agent"]["sub"]["usd"], 2.5)
        self.assertEqual(c["by_agent"]["sub"]["node"], "T01")
        self.assertIs(c["by_agent"]["sub"]["estimated"], True)
        self.assertIs(c["by_node"]["T01"]["estimated"], True)
        self.assertIs(c["estimated"], True)

    def test_by_agent_splits_the_real_cost_too(self):
        self._src("m.jsonl", "ORCH", "main", [
            asst("a", "claude-sonnet-5-5", 1000000, 0),
            json.dumps({"type": "cost-state", "sessionId": "S", "totalCostUSD": 6.0, "modelUsage": {}})])
        self._src("sub.jsonl", "T01", "agent", [asst("b", "claude-sonnet-5-5", 1000000, 0)])
        d = tokens.build(self.root)
        self.assertEqual(d["cost"]["usd"], 6.0)
        self.assertIs(d["cost"]["estimated"], False)
        self.assertAlmostEqual(d["by_agent"]["m"]["cost_usd"], 3.0)      # stessi token: metà ciascuno
        self.assertAlmostEqual(d["by_agent"]["sub"]["cost_usd"], 3.0)
        self.assertIs(d["by_agent"]["sub"]["estimated"], False)
        self.assertEqual(d["by_agent"]["sub"]["node"], "T01")

    def test_by_node_models_are_dicts(self):
        self._src("m.jsonl", "T01", "agent", [asst("a", "claude-sonnet-5-5", 10, 5, cr=100, cc=20),
                                              asst("b", "claude-opus-5-5", 1, 1)])
        d = tokens.build(self.root)
        m = d["by_node"]["T01"]["models"]
        self.assertEqual(m["claude-sonnet-5-5"],
                         {"input": 10, "output": 5, "cache_read": 100, "cache_creation": 20, "total": 135})
        self.assertEqual(m["claude-opus-5-5"]["total"], 2)
        self.assertEqual(d["by_agent"]["m"]["models"]["claude-opus-5-5"]["total"], 2)

    def test_old_integer_models_form_still_readable(self):
        old = {"by_node": {"T01": {"input": 50000, "output": 0, "cache_read": 0, "cache_creation": 0, "total": 50000,
                                   "turns": 1, "categories": {}, "models": {"claude-opus-5-5": 50000}}}}
        state = {"nodes": [{"id": "T01", "status": "validated", "attempts": 0, "files": ["a"]}]}
        rep = tokens.analyze(old, state)
        self.assertTrue(any(i["kind"] == "model" for i in rep["insights"]))
        self.assertEqual(tokens._mtotal(50000), 50000)
        self.assertEqual(tokens._mtotal({"total": 7}), 7)


if __name__ == "__main__":
    unittest.main()
