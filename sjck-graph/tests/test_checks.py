import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)

import checks  # noqa: E402


def card(*crit):
    return "# T\n## Obiettivo\nx\n## Criteri di accettazione\n" + \
        "".join("- %s\n" % c for c in crit) + "## Fuori scope\n-\n"


class Spy:
    """Doppio del validatore LLM: conta le invocazioni."""
    def __init__(self, verdict="pass"):
        self.calls = []
        self.verdict = verdict

    def __call__(self, model):
        self.calls.append(model)
        return self.verdict


class TestLevel1(unittest.TestCase):
    def test_pass(self):
        r = checks.run_checks(card("`true` → exit 0"))
        self.assertEqual(r["outcome"], "pass")

    def test_fail_has_output(self):
        r = checks.run_checks(card("`echo boom; exit 3` -> exit 0"))
        self.assertEqual(r["outcome"], "fail")
        self.assertIn("boom", r["output"])

    def test_expected_nonzero_exit(self):
        self.assertEqual(checks.run_checks(card("`exit 3` → exit 3"))["outcome"], "pass")

    def test_fail_dominates_pass(self):
        r = checks.run_checks(card("`true` → exit 0", "`false` → exit 0"))
        self.assertEqual(r["outcome"], "fail")

    def test_no_criteria_is_ambiguous(self):
        self.assertEqual(checks.run_checks("# T\n## Obiettivo\nx\n")["outcome"], "ambiguous")

    def test_only_prose_is_ambiguous(self):
        r = checks.run_checks(card("il diff e' minimo", "`file.py` resta invariato"))
        self.assertEqual(r["outcome"], "ambiguous")

    def test_uninterpretable_expectation_is_ambiguous_and_not_run(self):
        r = checks.run_checks(card("`touch /nonexistent/x` → qualcosa di strano"))
        self.assertEqual(r["outcome"], "ambiguous")
        self.assertNotIn("code", r["checks"][0])

    def test_zero_failures_phrase(self):
        r = checks.run_checks(card("`true` → 0 fallimenti"))
        self.assertEqual(r["outcome"], "pass")

    def test_runs_in_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "f.txt"), "w").close()
            self.assertEqual(checks.run_checks(card("`test -f f.txt` → exit 0"), d)["outcome"], "pass")


class TestTwoLevels(unittest.TestCase):
    CFG = {"model": "haiku", "timeout": 30}

    def test_fail_never_invokes_llm(self):
        spy = Spy()
        r = checks.validate(card("`false` → exit 0"), spy, config=self.CFG)
        self.assertEqual(len(spy.calls), 0)
        self.assertEqual(spy.calls, [])
        self.assertEqual((r["action"], r["verdict"], r["llm_invoked"]), ("retry", "fail", False))

    def test_fail_never_invokes_llm_even_if_card_requires_it(self):
        spy = Spy()
        checks.validate(card("`false` → exit 0", "validator: llm"), spy, config=self.CFG)
        self.assertEqual(len(spy.calls), 0)

    def test_pass_does_not_invoke_llm(self):
        spy = Spy()
        r = checks.validate(card("`true` → exit 0"), spy, config=self.CFG)
        self.assertEqual(len(spy.calls), 0)
        self.assertEqual(r["verdict"], "pass")

    def test_ambiguous_invokes_llm_with_configured_model(self):
        spy = Spy("fail")
        r = checks.validate(card("il diff e' minimo"), spy, config=self.CFG)
        self.assertEqual(spy.calls, ["haiku"])
        self.assertEqual((r["action"], r["verdict"]), ("llm", "fail"))

    def test_card_can_require_llm_after_pass(self):
        spy = Spy()
        checks.validate(card("`true` → exit 0", "validator: llm"), spy, config=self.CFG)
        self.assertEqual(len(spy.calls), 1)


class TestConfig(unittest.TestCase):
    def test_default_from_versioned_file(self):
        with tempfile.TemporaryDirectory() as d:
            with open(checks.DEFAULT_CONFIG, encoding="utf-8") as f:
                self.assertEqual(checks.load_config(d)["model"], json.load(f)["model"])

    def test_override_wins_and_haiku_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".sjck"))
            with open(os.path.join(d, ".sjck", "validation.json"), "w") as f:
                json.dump({"model": "haiku"}, f)
            self.assertEqual(checks.load_config(d)["model"], "haiku")
            spy = Spy()
            checks.validate(card("prosa"), spy, cwd=d)
            self.assertEqual(spy.calls, ["haiku"])

    def test_invalid_model_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".sjck"))
            with open(os.path.join(d, ".sjck", "validation.json"), "w") as f:
                json.dump({"model": "gpt"}, f)
            with self.assertRaises(ValueError):
                checks.load_config(d)

    def test_default_model_is_valid_enum(self):
        with open(checks.DEFAULT_CONFIG, encoding="utf-8") as f:
            self.assertIn(json.load(f)["model"], checks.MODELS)


class TestCli(unittest.TestCase):
    def run_cli(self, text):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".sjck", "cards"))
            with open(os.path.join(d, ".sjck", "cards", "T1.md"), "w") as f:
                f.write(text)
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "checks.py"),
                                "run", "T1", "--cwd", d], stdout=subprocess.PIPE,
                               universal_newlines=True)
            return p.returncode, json.loads(p.stdout)

    def test_exit_codes(self):
        self.assertEqual(self.run_cli(card("`true` → exit 0"))[0], 0)
        self.assertEqual(self.run_cli(card("`false` → exit 0"))[0], 1)
        code, out = self.run_cli("# T\n## Obiettivo\nx\n")
        self.assertEqual(code, 2)
        self.assertTrue(out["invoke_llm"])


if __name__ == "__main__":
    unittest.main()
