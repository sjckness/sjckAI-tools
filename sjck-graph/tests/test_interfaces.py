import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import interfaces  # noqa: E402
import cards  # noqa: E402

CARD = "# T9 — x\n" + "".join(
    "## %s\n%s corpo %s\n\n" % (t, t, "y" * 50) for t in cards.SECTIONS)


class Reuse(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, ".sjck", "interfaces"))
        self.src = os.path.join(self.d, "a.py")
        with open(self.src, "w") as f:
            f.write("def f(): pass\n")
        with open(os.path.join(self.d, ".sjck", "interfaces", "api.md"), "w") as f:
            f.write("f()")

    def test_unregistered_stale(self):
        self.assertEqual(interfaces.check(self.d, "api"), "stale")

    def test_unchanged_fresh(self):
        interfaces.register(self.d, "api", ["a.py"])
        self.assertEqual(interfaces.check(self.d, "api"), "fresh")

    def test_one_byte_stale(self):
        interfaces.register(self.d, "api", ["a.py"])
        with open(self.src, "a") as f:
            f.write("#")
        self.assertEqual(interfaces.check(self.d, "api"), "stale")

    def test_invalidate(self):
        interfaces.register(self.d, "api", ["a.py"])
        self.assertTrue(interfaces.invalidate(self.d, "api"))
        self.assertEqual(interfaces.check(self.d, "api"), "stale")

    def test_missing_source_stale(self):
        interfaces.register(self.d, "api", ["a.py"])
        os.remove(self.src)
        self.assertEqual(interfaces.check(self.d, "api"), "stale")


class Selective(unittest.TestCase):
    def test_two_sections(self):
        out = cards.select_sections(CARD, ("Obiettivo", "Fuori scope"))
        self.assertEqual(list(cards.parse_card(out)), ["Obiettivo", "Fuori scope"])
        self.assertLess(len(out), len(CARD))

    def test_state(self):
        st = {"nodes": [{"id": "A", "status": "done", "files": ["f"], "x": 1},
                        {"id": "B", "deps": ["A"], "status": "pending"},
                        {"id": "C"}], "other": "big"}
        out = cards.select_state(st, "B")
        self.assertEqual([n["id"] for n in out["nodes"]], ["B", "A"])
        self.assertNotIn("x", out["nodes"][1])
        self.assertNotIn("other", out)


class PromptOrder(unittest.TestCase):
    def test_invariant_first(self):
        for card, corr in (("CARD-uno", ""), ("CARD-due lunga", "CORR-fix")):
            p = cards.build_prompt("SYS", "FUORI", "BUDGET", card, corr)
            tail = [p.index(x) for x in (card, corr) if x]
            for inv in ("SYS", "FUORI", "BUDGET"):
                self.assertLess(p.index(inv), min(tail))
            self.assertLess(p.index("SYS"), p.index("FUORI"))
            self.assertLess(p.index("FUORI"), p.index("BUDGET"))


class CardsCli(unittest.TestCase):
    CARD = ("# T9\n## Obiettivo\nlungo testo\n## Puoi modificare\n- `a.py`\n"
            "## Criteri di accettazione\n- `true` -> exit 0\n## Fuori scope\n- x\n")

    def setUp(self):
        import io
        import json
        import contextlib
        self.io, self.json, self.cl = io, json, contextlib
        self.d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.d, True)
        os.makedirs(os.path.join(self.d, ".sjck", "cards"))
        with open(os.path.join(self.d, ".sjck", "cards", "T9.md"), "w") as f:
            f.write(self.CARD)
        st = {"nodes": [{"id": "T9", "deps": ["T8"], "status": "running", "files": ["a.py"]},
                        {"id": "T8", "status": "validated", "files": ["b.py"], "summary": "x"},
                        {"id": "T1", "status": "validated"}]}
        with open(os.path.join(self.d, ".sjck", "state.json"), "w") as f:
            json.dump(st, f)

    def run_cli(self, *argv):
        out = self.io.StringIO()
        with self.cl.redirect_stdout(out):
            code = cards.main(list(argv))
        return code, out.getvalue()

    def test_sections_writes_reduced_card(self):
        code, out = self.run_cli("sections", "T9", "--cwd", self.d)
        self.assertEqual(code, 0)
        dest = os.path.join(self.d, ".sjck", "out", "T9.card.md")
        self.assertEqual(out.strip(), dest)
        with open(dest) as f:
            txt = f.read()
        self.assertIn("## Criteri di accettazione", txt)
        self.assertNotIn("Obiettivo", txt)

    def test_state_slice(self):
        code, out = self.run_cli("state", "T9", "--cwd", self.d)
        self.assertEqual(code, 0)
        ids = [n["id"] for n in self.json.loads(out)["nodes"]]
        self.assertEqual(ids, ["T9", "T8"])

    def test_prompt_order(self):
        fs = {}
        for k, v in (("system", "SYS"), ("fuori", "OUT"), ("budget", "BUD"), ("card", "CARD"), ("corr", "COR")):
            fs[k] = os.path.join(self.d, k)
            with open(fs[k], "w") as f:
                f.write(v)
        code, out = self.run_cli("prompt", "--system", fs["system"], "--fuori-scope", fs["fuori"],
                                 "--budget", fs["budget"], "--card", fs["card"],
                                 "--correzioni", fs["corr"])
        self.assertEqual(code, 0)
        self.assertEqual(out.split(), ["SYS", "OUT", "BUD", "CARD", "COR"])

    def test_missing_card_exit_1(self):
        err = self.io.StringIO()
        with self.cl.redirect_stderr(err):
            code, _ = self.run_cli("sections", "NOPE", "--cwd", self.d)
        self.assertEqual(code, 1)

    def test_help_exit_0(self):
        with self.assertRaises(SystemExit) as cm, self.cl.redirect_stdout(self.io.StringIO()):
            cards.main(["--help"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
