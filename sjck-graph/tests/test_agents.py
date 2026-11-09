import os
import re
import unittest

AGENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents")

# Prima colonna delle righe `no` di .sjck/interfaces/cc-subagents.md: nessuna riga `no`.
UNSUPPORTED = set()

EXPECTED = {
    "sjck-planner": ("opus", "high"),
    "sjck-scout": ("haiku", "low"),
    "sjck-implementer": ("sonnet", "medium"),
    "sjck-validator": ("sonnet", "high"),
    "sjck-reviewer": ("opus", "high"),
    "sjck-critic": ("fable", "high"),
}
FALLBACK = {"xhigh": "high", "max": "high"}


def parse(name):
    with open(os.path.join(AGENTS, name + ".md"), encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, "frontmatter mancante in " + name
    fm = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm


def text(name):
    with open(os.path.join(AGENTS, name + ".md"), encoding="utf-8") as f:
        return f.read()


class TestAgents(unittest.TestCase):
    def test_defaults(self):
        for name, (model, effort) in EXPECTED.items():
            with self.subTest(agent=name):
                fm = parse(name)
                self.assertEqual(fm["name"], name)
                self.assertTrue(fm.get("description"))
                self.assertEqual(fm.get("model"), model)
                self.assertEqual(fm.get("effort"), effort)

    def test_unsupported_absent_or_fallback(self):
        for name in EXPECTED:
            fm = parse(name)
            for key, val in fm.items():
                self.assertNotIn(key, UNSUPPORTED, name)
                self.assertNotIn(f"{key}: {val}", UNSUPPORTED, name)
                if key == "effort":
                    self.assertNotIn(val, FALLBACK, name)

    def test_max_turns(self):
        for name in ("sjck-scout", "sjck-implementer", "sjck-validator", "sjck-critic"):
            with self.subTest(agent=name):
                self.assertTrue(re.fullmatch(r"\d+", parse(name).get("maxTurns", "")))
        self.assertGreaterEqual(int(parse("sjck-implementer")["maxTurns"]), 100)
        self.assertLessEqual(int(parse("sjck-critic")["maxTurns"]), 5)

    def test_omit_claude_md(self):
        for name in EXPECTED:
            with self.subTest(agent=name):
                self.assertEqual(parse(name).get("omitClaudeMd"), "true")

    def test_critic(self):
        fm = parse("sjck-critic")
        self.assertEqual(fm["tools"], "Read, Grep")
        with open(os.path.join(AGENTS, "sjck-critic.md"), encoding="utf-8") as f:
            self.assertIn('"verdict"', f.read())

    def test_tools_unchanged(self):
        self.assertEqual(parse("sjck-planner")["tools"], "Read, Grep, Glob, Write")
        self.assertEqual(parse("sjck-scout")["tools"], "Read, Grep, Glob, Write")
        self.assertEqual(parse("sjck-implementer")["tools"], "Read, Edit, Write, Bash, Grep, Glob")
        self.assertEqual(parse("sjck-validator")["tools"], "Read, Grep, Glob, Bash")
        self.assertEqual(parse("sjck-reviewer")["tools"], "Read, Grep, Bash")

    def test_script_path_from_prompt(self):
        for name in ("sjck-implementer", "sjck-validator", "sjck-reviewer"):
            with self.subTest(agent=name):
                t = text(name)
                for s in ("script:", "<script>/findings.py",
                          "${CLAUDE_PLUGIN_ROOT}/scripts", "sjck-scripts"):
                    self.assertIn(s, t)

    def test_reviewer_from_review(self):
        t = text("sjck-reviewer")
        self.assertIn("--from REVIEW", t)
        self.assertNotIn("--from <ID>", t)

    def test_assumptions_in_outputs(self):
        for name in ("sjck-validator", "sjck-reviewer"):
            self.assertIn('"assumptions"', text(name))

    def test_planner_findings_format(self):
        self.assertIn('"kind":"bug|smell|debt|doc|loop"', text("sjck-planner"))

    def test_critic_out_of_scope(self):
        self.assertIn("fuori scope", text("sjck-critic"))

    def test_graph_view_fallback(self):
        with open(os.path.join(AGENTS, "..", "commands", "sjck-view.md"),
                  encoding="utf-8") as f:
            t = f.read()
        self.assertIn("sjck-scripts/graph_view.py", t)
        self.assertIn("~/.claude/plugins/", t)


if __name__ == "__main__":
    unittest.main()
