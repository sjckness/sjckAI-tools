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


if __name__ == "__main__":
    unittest.main()
