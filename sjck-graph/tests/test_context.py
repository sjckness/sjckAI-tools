"""P2 — dieta del contesto: categorie piu' pesanti, interfacce per hash, card per ruolo."""
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
import context  # noqa: E402

CARD = """# T01 — titolo
## Obiettivo
Estrarre l'interfaccia del nodo.
## Puoi modificare
- `.sjck/interfaces/api.md`
## Leggi
- `src/api.py`
- `src/pkg/`
## Criteri di accettazione
- `python3 -m unittest` esce 0
## Fuori scope
- Il bug noto in `src/legacy.py`
## Correzioni richieste
- Manca il tipo di ritorno di `send()`
"""


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sjck-ctx-")
        for d in ("cards", "out", "interfaces"):
            os.makedirs(os.path.join(self.root, ".sjck", d))
        self._card("T01", CARD)
        os.makedirs(os.path.join(self.root, "src", "pkg"))
        self._src("src/api.py", "def send(): pass\n")
        self._src("src/pkg/a.py", "A = 1\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _card(self, nid, text):
        with open(os.path.join(self.root, ".sjck", "cards", nid + ".md"), "w", encoding="utf-8") as f:
            f.write(text)

    def _src(self, rel, text):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    def _state(self, state):
        with open(os.path.join(self.root, ".sjck", "state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f)

    def _tokens(self, cats):
        with open(os.path.join(self.root, ".sjck", "tokens.json"), "w", encoding="utf-8") as f:
            json.dump({"by_node": {"T01": {"categories": cats}}}, f)

    # ---- top: quali categorie attaccare

    def test_top_names_the_two_heaviest_categories_with_an_action(self):
        self._tokens({"system": 100, "file_read_in_card": 60, "card": 10})
        t = context.top(self.root)
        self.assertEqual([x["category"] for x in t["top"]], ["system", "file_read_in_card"])
        self.assertEqual(t["top"][0]["share"], 58.8)
        self.assertIn("checks.py", t["top"][0]["action"])
        self.assertIn("interfacce riusate", t["top"][1]["action"])

    def test_top_without_data_says_so(self):
        self.assertIn("note", context.top(self.root))

    # ---- interfacce riusabili per hash

    def _iface(self, name="api", where=None):
        d = where or os.path.join(self.root, ".sjck", "interfaces")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name + ".md"), "w", encoding="utf-8") as f:
            f.write("send() -> None  src/api.py:1\n")

    def test_record_then_fresh_then_stale_when_a_source_changes(self):
        self._iface()
        meta = context.record(self.root, "api", ["src/api.py", "src/pkg/"])
        self.assertIn("src/api.py", meta["files"])
        self.assertIn("src/pkg/a.py", meta["files"], "una cartella si espande nei suoi file")
        self.assertEqual(context.check(self.root, "api")["status"], "fresh")
        self._src("src/api.py", "def send(x): pass\n")
        r = context.check(self.root, "api")
        self.assertEqual(r["status"], "stale")
        self.assertEqual(r["changed"], ["src/api.py"])
        # un file nuovo nella cartella rende stale l'interfaccia
        context.record(self.root, "api", ["src/api.py", "src/pkg/"])
        self._src("src/pkg/b.py", "B = 2\n")
        self.assertEqual(context.check(self.root, "api")["status"], "stale")

    def test_missing_interface_or_missing_hash_is_not_reusable(self):
        self.assertEqual(context.check(self.root, "api")["status"], "missing")
        self._iface()
        self.assertEqual(context.check(self.root, "api")["status"], "missing", "md senza hash")

    def test_reuse_restores_a_fresh_interface_from_the_archive(self):
        arch = os.path.join(self.root, ".sjck", "archive", "20261101-1200", "interfaces")
        self._iface(where=arch)
        meta = context.record(self.root, "api", ["src/api.py"])
        shutil.move(context.iface_meta_path(self.root, "api"), os.path.join(arch, "api.json"))
        self.assertFalse(os.path.exists(context.iface_md_path(self.root, "api")))
        r = context.reuse(self.root, "api")
        self.assertEqual((r["status"], r["reused"]), ("fresh", "from archive"))
        self.assertTrue(os.path.isfile(context.iface_md_path(self.root, "api")))
        self.assertEqual(json.load(open(context.iface_meta_path(self.root, "api")))["files"], meta["files"])
        # sorgente cambiata: dall'archivio non si riusa piu'
        shutil.rmtree(os.path.join(self.root, ".sjck", "interfaces"))
        self._src("src/api.py", "altro\n")
        self.assertEqual(context.reuse(self.root, "api")["status"], "missing")

    def test_skippable_lists_scout_nodes_whose_interfaces_are_fresh(self):
        self._state({"nodes": [{"id": "T01", "agent": "scout", "status": "pending"},
                               {"id": "T02", "agent": "implementer", "status": "pending"}]})
        self._iface()
        context.record(self.root, "api", ["src/api.py"])
        s = context.skippable(self.root)
        self.assertEqual([x["id"] for x in s["reusable"]], ["T01"], "T02 non e' uno scout")
        self.assertEqual(s["reusable"][0]["interfaces"], ["api"])
        self._src("src/api.py", "cambiato\n")
        s = context.skippable(self.root)
        self.assertEqual(s["reusable"], [])
        self.assertIn("stale", s["regenerate"][0]["reason"])

    # ---- card e stato ridotti

    def test_validator_slice_drops_the_read_list_and_keeps_the_criteria(self):
        full = context.card_slice(CARD, "implementer")
        val = context.card_slice(CARD, "validator")
        self.assertIn("## Leggi", full)
        self.assertNotIn("## Leggi", val)
        self.assertNotIn("src/api.py", val)
        self.assertIn("## Criteri di accettazione", val)
        self.assertIn("## Puoi modificare", val)
        self.assertIn("## Fuori scope", val)
        self.assertNotIn("## Correzioni richieste", val, "al primo tentativo non servono")
        self.assertLess(len(val), len(full))
        retry = context.card_slice(CARD, "validator", attempt=1)
        self.assertIn("## Correzioni richieste", retry)
        self.assertIn("## Criteri di accettazione", context.card_slice(CARD, "critic"))
        self.assertNotIn("## Fuori scope", context.card_slice(CARD, "critic"))

    def test_prompt_has_the_same_stable_prefix_for_every_node(self):
        self._card("T02", CARD.replace("T01", "T02"))
        self._state({"goal": "g", "nodes": [{"id": "T01", "budget": {"tool_calls": 40}},
                                            {"id": "T02", "budget": {"tool_calls": 60}}]})
        a = context.node_prompt(self.root, "T01", "implementer", "/abs/scripts")
        b = context.node_prompt(self.root, "T02", "implementer", "/abs/scripts")
        pa = a.split("--- nodo ---")[0]
        self.assertEqual(pa, b.split("--- nodo ---")[0], "prefisso stabile = cache condivisa")
        self.assertTrue(a.startswith("ruolo: implementer\nscript: /abs/scripts"))
        self.assertIn("id: T01", a)
        self.assertIn("budget: max 40 tool call", a)
        self.assertIn("## Obiettivo", a)
        self.assertNotIn("tentativo:", a)
        self.assertIn("tentativo: 2", context.node_prompt(self.root, "T01", "implementer", "/x", attempt=2))
        # il validatore riceve la card ridotta
        v = context.node_prompt(self.root, "T01", "validator", "/x")
        self.assertNotIn("## Leggi", v)

    def test_prompt_says_when_the_card_is_missing(self):
        self.assertIn("card: MANCANTE", context.node_prompt(self.root, "TXX", "implementer"))

    def _quiet(self):
        ctx = redirect_stdout(io.StringIO())
        ctx.__enter__()
        return lambda: ctx.__exit__(None, None, None)

    def test_state_slice_is_goal_node_and_deps_only(self):
        self._state({"goal": "g", "mode": "L", "log": ["x"] * 50, "nodes": [
            {"id": "T01", "status": "validated", "files": ["a"], "agent_id": "a1"},
            {"id": "T02", "status": "pending", "deps": ["T01"], "files": ["b"], "budget": {"tool_calls": 40}}]})
        s = context.state_slice(self.root, "T02")
        self.assertEqual(s["goal"], "g")
        self.assertEqual(s["node"]["id"], "T02")
        self.assertEqual(s["deps"], [{"id": "T01", "status": "validated", "files": ["a"]}])
        self.assertNotIn("log", json.dumps(s))
        self.assertNotIn("agent_id", json.dumps(s))

    def test_cli(self):
        self.addCleanup(self._quiet())
        self._tokens({"system": 10, "card": 5})
        self.assertEqual(context.main(["--cwd", self.root, "top"]), 0)
        self.assertEqual(context.main(["--cwd", self.root, "card", "--id", "T01", "--role", "validator"]), 0)
        self.assertEqual(context.main(["--cwd", self.root, "card", "--id", "NOPE"]), 3)
        self._iface()
        self.assertEqual(context.main(["--cwd", self.root, "interfaces", "record",
                                       "--name", "api", "--from-card", "T01"]), 0)
        self.assertEqual(context.main(["--cwd", self.root, "interfaces", "check", "--name", "api"]), 0)
        self._src("src/api.py", "x\n")
        self.assertEqual(context.main(["--cwd", self.root, "interfaces", "check", "--name", "api"]), 1)
        self.assertEqual(context.main(["--cwd", self.root, "interfaces", "record", "--name", "api"]), 3)


if __name__ == "__main__":
    unittest.main()
