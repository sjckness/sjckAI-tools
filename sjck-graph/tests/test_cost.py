"""P1 — costo in dollari per nodo, agente e run (prezzi configurabili)."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import config  # noqa: E402
import tokens  # noqa: E402

M = 1e6


def asst(mid, model, inp=0, out=0, cr=0, cc=0, stop="end_turn"):
    return json.dumps({"type": "assistant", "timestamp": "2026-11-09T10:00:00Z", "message": {
        "id": mid, "role": "assistant", "model": model, "stop_reason": stop, "content": [],
        "usage": {"input_tokens": inp, "output_tokens": out,
                  "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc}}})


class PricesTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="sjck-home-")
        self.root = tempfile.mkdtemp(prefix="sjck-proj-")
        os.makedirs(os.path.join(self.root, ".sjck"))
        self.env = dict(os.environ)
        os.environ["HOME"] = self.home
        for k in ("SJCK_PRICES", "SJCK_CONFIG", "SJCK_VALIDATOR_MODEL", "SJCK_VALIDATOR_EFFORT"):
            os.environ.pop(k, None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, path, obj):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def test_shipped_table_has_input_output_and_cache_multipliers(self):
        t = config.load_prices()
        r = config.rates("claude-opus-5-5", t)
        self.assertAlmostEqual(r["input"], 4.0 / M)
        self.assertAlmostEqual(r["output"], 20.0 / M)
        # cache write: moltiplicatore 1,25 sull'input; cache read: prezzo esplicito del modello
        self.assertAlmostEqual(r["cache_creation"], 4.0 * 1.25 / M)
        self.assertAlmostEqual(r["cache_read"], 0.2 / M)
        # un modello senza prezzo esplicito di cache read usa il moltiplicatore 0,1
        self.assertAlmostEqual(config.rates("claude-opus-5", t)["cache_read"], 5.0 * 0.1 / M)

    def test_unknown_model_is_not_invented(self):
        t = config.load_prices()
        self.assertIsNone(config.rates("gpt-qualcosa", t))
        self.assertIsNone(config.rates("<synthetic>", t))
        self.assertEqual(config.cost_of({"input": 10 ** 6}, "modello-ignoto", t), (0.0, False))

    def test_provider_prefixes_and_suffixes_match_the_same_price(self):
        t = config.load_prices()
        base = config.rates("claude-sonnet-5-5", t)
        for name in ("us.anthropic.claude-sonnet-5-5-v1:0", "CLAUDE-SONNET-5-5",
                     "claude-sonnet-5-5@20261101"):
            self.assertEqual(config.rates(name, t), base, name)

    def test_cost_of_sums_the_four_token_types(self):
        t = config.load_prices()
        counts = {"input": 1000, "output": 2000, "cache_read": 10000, "cache_creation": 4000}
        usd, priced = config.cost_of(counts, "claude-opus-5-5", t)
        want = (1000 * 4.0 + 2000 * 20.0 + 10000 * 0.2 + 4000 * 5.0) / M
        self.assertTrue(priced)
        self.assertAlmostEqual(usd, want)

    def test_override_project_user_env_without_touching_code(self):
        self._write(os.path.join(self.home, ".sjck", "prices.json"),
                    {"models": {"claude-opus-5-5": {"input": 9.0}}})
        t = config.load_prices(self.root)
        self.assertAlmostEqual(config.rates("claude-opus-5-5", t)["input"], 9.0 / M)
        self.assertAlmostEqual(config.rates("claude-opus-5-5", t)["output"], 20.0 / M, msg="campo non toccato")
        # il progetto vince sull'utente, e puo' aggiungere un modello nuovo
        self._write(os.path.join(self.root, ".sjck", "prices.json"),
                    {"models": {"claude-opus-5-5": {"input": 1.0}, "modello-interno": {"input": 2.0, "output": 3.0}},
                     "cache_multipliers": {"cache_read": 0.5}})
        t = config.load_prices(self.root)
        self.assertAlmostEqual(config.rates("claude-opus-5-5", t)["input"], 1.0 / M)
        self.assertAlmostEqual(config.rates("modello-interno", t)["cache_read"], 2.0 * 0.5 / M)
        # $SJCK_PRICES vince su tutti e puo' togliere un modello (null) -> solo token
        p = os.path.join(self.root, "listino.json")
        self._write(p, {"models": {"claude-opus-5-5": None, "modello-interno": {"input": 7.0, "output": 8.0}}})
        os.environ["SJCK_PRICES"] = p
        t = config.load_prices(self.root)
        self.assertIsNone(config.rates("claude-opus-5-5", t))
        self.assertAlmostEqual(config.rates("modello-interno", t)["input"], 7.0 / M)

    # ---- integrazione con tokens.py

    def _run(self, lines_by_label, state_nodes=("T01",)):
        os.environ["SJCK_FX_OFFLINE"] = "1"
        os.environ["SJCK_EUR_PER_USD"] = "0.5"
        self._write(os.path.join(self.root, ".sjck", "state.json"),
                    {"status": "running", "nodes": [{"id": n} for n in state_nodes]})
        for label, lines in lines_by_label.items():
            p = os.path.join(self.root, label + ".jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            tokens.add_source(self.root, p, label, "main" if label == "ORCH" else "agent")
        return tokens.build(self.root)

    def test_estimated_cost_per_node_and_model_without_cost_state(self):
        d = self._run({
            "ORCH": [asst("o1", "claude-opus-5-5", inp=1000, out=2000, cr=10000, cc=4000)],
            "T01": [asst("t1", "claude-haiku-5-5", inp=1000, out=1000)],
        })
        orch = (1000 * 4.0 + 2000 * 20.0 + 10000 * 0.2 + 4000 * 5.0) / M
        t01 = (1000 * 0.1 + 1000 * 0.5) / M
        self.assertEqual(d["cost"]["source"], "prices")
        self.assertTrue(d["cost"]["estimated"])
        self.assertAlmostEqual(d["cost"]["usd"], round(orch + t01, 4), places=4)
        self.assertAlmostEqual(d["by_node"]["ORCH"]["cost_usd"], round(orch, 4), places=4)
        self.assertAlmostEqual(d["by_node"]["T01"]["cost_usd"], round(t01, 4), places=4)
        self.assertTrue(d["by_node"]["T01"]["cost_estimated"])
        self.assertAlmostEqual(d["by_model"]["claude-haiku-5-5"]["cost_usd"], round(t01, 4), places=4)
        self.assertEqual(d["cost"]["prices_updated"], config.load_prices()["updated"])
        self.assertAlmostEqual(d["cost"]["eur"], round(d["cost"]["usd"] * 0.5, 4), places=4)

    def test_real_cost_wins_and_is_split_with_the_price_table(self):
        d = self._run({
            # 1 token di output su opus (20 $/M) contro 1 su haiku (0,5 $/M): 40:1
            "ORCH": [asst("o1", "claude-opus-5-5", out=10 ** 6),
                     json.dumps({"type": "cost-state", "sessionId": "S", "totalCostUSD": 41.0,
                                 "modelUsage": {"claude-opus-5-5": {"costUSD": 40.0},
                                                "claude-haiku-5-5": {"costUSD": 1.0}}})],
            "T01": [asst("t1", "claude-haiku-5-5", out=10 ** 6)],
        })
        self.assertEqual(d["cost"]["source"], "cost-state")
        self.assertFalse(d["cost"]["estimated"])
        self.assertEqual(d["cost"]["usd"], 41.0)
        self.assertEqual(d["cost"]["split"], "per-node shares from prices.json")
        self.assertAlmostEqual(d["by_node"]["ORCH"]["cost_usd"], 40.0, places=2)
        self.assertAlmostEqual(d["by_node"]["T01"]["cost_usd"], 1.0, places=2)
        self.assertFalse(d["by_node"]["T01"]["cost_estimated"])
        self.assertAlmostEqual(d["cost"]["estimate_usd"], 20.5, places=2)

    def test_model_without_price_shows_tokens_only(self):
        d = self._run({"ORCH": [asst("o1", "modello-di-casa", inp=1000, out=1000)]})
        self.assertIsNone(d["cost"])
        self.assertNotIn("cost_usd", d["by_node"]["ORCH"])
        self.assertEqual(d["by_node"]["ORCH"]["total"], 2000)
        # con un secondo nodo prezzato, il modello senza prezzo resta dichiarato
        d = self._run({"ORCH": [asst("o1", "modello-di-casa", inp=1000)],
                       "T01": [asst("t1", "claude-haiku-5-5", inp=1000)]})
        self.assertEqual(d["cost"]["unpriced_models"], ["modello-di-casa"])
        self.assertNotIn("cost_usd", d["by_node"]["ORCH"])
        self.assertIn("cost_usd", d["by_node"]["T01"])

    def test_report_carries_the_cost_and_the_saving_in_dollars(self):
        self._write(os.path.join(self.root, ".sjck", "state.json"),
                    {"status": "running", "nodes": [
                        {"id": "T01", "status": "failed", "agent_id": "a1", "files": ["src/x.py"]}]})
        p = os.path.join(self.root, "a1.jsonl")
        with open(p, "w", encoding="utf-8") as f:
            f.write(asst("s1", "claude-sonnet-5-5", inp=100000, out=1000) + "\n")
        os.environ["SJCK_FX_OFFLINE"] = "1"
        tokens.from_hook({"hook_event_name": "SubagentStop", "cwd": self.root,
                          "agent_id": "a1", "agent_transcript_path": p})
        with open(os.path.join(self.root, ".sjck", "token-report.json"), encoding="utf-8") as f:
            rep = json.load(f)
        self.assertTrue(rep["cost"]["estimated"])
        self.assertIn("T01", rep["cost"]["by_node"])
        waste = [i for i in rep["insights"] if i["kind"] == "waste"]
        self.assertTrue(waste, "nodo failed segnalato")
        self.assertGreater(waste[0]["saving_usd"], 0)
        self.assertAlmostEqual(waste[0]["cost_usd"], rep["cost"]["by_node"]["T01"], places=4)

    def test_cli_marks_the_estimate(self):
        self._run({"ORCH": [asst("o1", "claude-opus-5-5", inp=1000)]})
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(tokens.main(["--cwd", self.root]), 0)
        self.assertIn("[estimated from prices.json]", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
