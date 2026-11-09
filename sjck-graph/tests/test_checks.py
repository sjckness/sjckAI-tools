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
import config  # noqa: E402


def card(*crit):
    # dichiara uno scope: senza `## Puoi modificare` il livello 1 e' `ambiguous`
    return "# T\n## Obiettivo\nx\n## Puoi modificare\n- `f.txt`\n## Criteri di accettazione\n" + \
        "".join("- %s\n" % c for c in crit) + "## Fuori scope\n-\n"


def git_init(d, files=("f.txt",)):
    """Repo git pulito con un commit iniziale (i file dati tracciati e invariati)."""
    for args in (["init", "-q"], ["config", "user.email", "a@b"], ["config", "user.name", "t"]):
        subprocess.run(["git"] + args, cwd=d, check=True)
    for n in files:
        with open(os.path.join(d, n), "w") as f:
            f.write("1\n")
    subprocess.run(["git", "add", "."], cwd=d, check=True)
    subprocess.run(["git", "commit", "-qm", "i", "--allow-empty"], cwd=d, check=True)


REPO = tempfile.mkdtemp()
git_init(REPO)


def tearDownModule():
    __import__("shutil").rmtree(REPO, True)


class Hermetic(unittest.TestCase):
    """HOME e $SJCK_* isolati: config.py legge ~/.sjck/config.json e l'ambiente."""

    def setUp(self):
        self._env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))
        home = tempfile.mkdtemp(prefix="sjck-home-")
        self.addCleanup(__import__("shutil").rmtree, home, True)
        os.environ["HOME"] = home
        for k in ("SJCK_CONFIG", "SJCK_VALIDATOR_MODEL", "SJCK_VALIDATOR_EFFORT"):
            os.environ.pop(k, None)


class Spy:
    """Doppio del validatore LLM: conta le invocazioni."""
    def __init__(self, verdict="pass"):
        self.calls = []
        self.verdict = verdict

    def __call__(self, model, green=(), residual=()):
        self.calls.append(model)
        self.args = (list(green), list(residual))
        return self.verdict


class TestLevel1(unittest.TestCase):
    def test_pass(self):
        r = checks.run_checks(card("`true` → exit 0"), REPO)
        self.assertEqual(r["outcome"], "pass")

    def test_fail_has_output(self):
        r = checks.run_checks(card("`echo boom; exit 3` -> exit 0"))
        self.assertEqual(r["outcome"], "fail")
        self.assertIn("boom", r["output"])

    def test_expected_nonzero_exit(self):
        self.assertEqual(checks.run_checks(card("`exit 3` → exit 3"), REPO)["outcome"], "pass")

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

    def test_oppure_is_ambiguous_and_not_run(self):
        r = checks.run_checks(card("`false` → esce 0 oppure 1"))
        self.assertEqual(r["outcome"], "ambiguous")
        self.assertNotIn("code", r["checks"][0])

    def test_prose_alongside_green_is_never_pass(self):
        r = checks.run_checks(card("`true` → exit 0", "il diff tocca solo i file in scope"), REPO)
        self.assertEqual(r["outcome"], "ambiguous")
        self.assertEqual(r["green"], ["true"])
        self.assertEqual(r["residual"], ["il diff tocca solo i file in scope"])

    def test_green_and_residual_split(self):
        r = checks.run_checks(card("`true` → ok", "`true` → esce 0 oppure 1", "prosa"), REPO)
        self.assertEqual(r["green"], ["true"])
        self.assertEqual(r["residual"], ["prosa", "`true` -> esce 0 oppure 1"])

    def test_all_executable_has_empty_residual(self):
        r = checks.run_checks(card("`true` → exit 0"), REPO)
        self.assertEqual((r["outcome"], r["residual"]), ("pass", []))

    def test_zero_failures_phrase(self):
        r = checks.run_checks(card("`true` → 0 fallimenti"), REPO)
        self.assertEqual(r["outcome"], "pass")

    def test_runs_in_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            git_init(d)
            self.assertEqual(checks.run_checks(card("`test -f f.txt` → exit 0"), d)["outcome"], "pass")


class TestTwoLevels(unittest.TestCase):
    CFG = {"model": "haiku", "timeout_s": 30}

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
        r = checks.validate(card("`true` → exit 0"), spy, REPO, config=self.CFG)
        self.assertEqual(len(spy.calls), 0)
        self.assertEqual(r["verdict"], "pass")

    def test_green_not_rerun_passed_to_llm(self):
        spy = Spy()
        checks.validate(card("`true` → exit 0", "prosa"), spy, REPO, config=self.CFG)
        self.assertEqual(spy.args, (["true"], ["prosa"]))

    def test_ambiguous_invokes_llm_with_configured_model(self):
        spy = Spy("fail")
        r = checks.validate(card("il diff e' minimo"), spy, config=self.CFG)
        self.assertEqual(spy.calls, ["haiku"])
        self.assertEqual((r["action"], r["verdict"]), ("llm", "fail"))

    def test_card_can_require_llm_after_pass(self):
        spy = Spy()
        checks.validate(card("`true` → exit 0", "validator: llm"), spy, REPO, config=self.CFG)
        self.assertEqual(len(spy.calls), 1)


class TestConfig(Hermetic):
    def _conf(self, d, validator):
        os.makedirs(os.path.join(d, ".sjck"), exist_ok=True)
        with open(os.path.join(d, ".sjck", "config.json"), "w") as f:
            json.dump({"validator": validator}, f)

    def test_default_from_config_py(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = checks.load_config(d)
            self.assertEqual(cfg["model"], config.DEFAULT_CONFIG["validator"]["model"])
            self.assertEqual(cfg["timeout_s"], config.DEFAULT_CONFIG["validator"]["timeout_s"])

    def test_override_wins_and_haiku_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            self._conf(d, {"model": "haiku"})
            self.assertEqual(checks.load_config(d)["model"], "haiku")
            spy = Spy()
            checks.validate(card("prosa"), spy, cwd=d)
            self.assertEqual(spy.calls, ["haiku"])

    def test_env_wins_over_the_project_file(self):
        with tempfile.TemporaryDirectory() as d:
            self._conf(d, {"model": "haiku"})
            os.environ["SJCK_VALIDATOR_MODEL"] = "opus"
            self.assertEqual(checks.load_config(d)["model"], "opus")

    def test_invalid_model_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            self._conf(d, {"model": "gpt"})
            with self.assertRaises(ValueError):
                checks.load_config(d)

    def test_invalid_effort_and_timeout_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            self._conf(d, {"effort": "turbo"})
            with self.assertRaises(ValueError):
                checks.load_config(d)
            self._conf(d, {"timeout_s": 0})
            with self.assertRaises(ValueError):
                checks.load_config(d)

    def test_always_llm_keeps_level_2_even_on_pass(self):
        with tempfile.TemporaryDirectory() as d:
            git_init(d)
            self._conf(d, {"model": "haiku", "always_llm": True})
            spy = Spy()
            r = checks.validate(card("`true` -> exit 0"), spy, cwd=d)
            self.assertEqual((r["outcome"], r["action"]), ("pass", "llm"))
            self.assertEqual(spy.calls, ["haiku"])

    def test_defaults_are_valid_enums(self):
        v = config.DEFAULT_CONFIG["validator"]
        self.assertIn(v["model"], checks.MODELS)
        self.assertIn(v["effort"], checks.EFFORTS)


class TestCli(Hermetic):
    def run_cli(self, text, override=None):
        with tempfile.TemporaryDirectory() as d:
            git_init(d)
            os.makedirs(os.path.join(d, ".sjck", "cards"))
            with open(os.path.join(d, ".sjck", "cards", "T1.md"), "w") as f:
                f.write(text)
            if override is not None:
                with open(os.path.join(d, ".sjck", "config.json"), "w") as f:
                    json.dump({"validator": override}, f)
            p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "checks.py"),
                                "run", "T1", "--cwd", d], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True)
            l1 = os.path.join(d, ".sjck", "out", "T1.l1.json")
            saved = None
            if os.path.isfile(l1):
                with open(l1) as f:
                    saved = json.load(f)
            out = json.loads(p.stdout) if p.stdout.strip() else None
            return p.returncode, out, p.stderr, saved

    def test_exit_codes(self):
        self.assertEqual(self.run_cli(card("`true` → exit 0"))[0], 0)
        self.assertEqual(self.run_cli(card("`false` → exit 0"))[0], 1)
        code, out, _, _ = self.run_cli("# T\n## Obiettivo\nx\n")
        self.assertEqual(code, 2)
        self.assertTrue(out["invoke_llm"])

    def test_fail_does_not_invoke_llm(self):
        _, out, _, _ = self.run_cli(card("`false` → exit 0", "validator: llm"))
        self.assertFalse(out["invoke_llm"])
        self.assertEqual(out["action"], "retry")

    def test_pass_with_validator_llm_invokes(self):
        code, out, _, _ = self.run_cli(card("`true` → exit 0", "validator: llm"))
        self.assertEqual(code, 0)
        self.assertTrue(out["invoke_llm"])

    def test_pass_without_llm_does_not_invoke(self):
        _, out, _, _ = self.run_cli(card("`true` → exit 0"))
        self.assertFalse(out["invoke_llm"])

    def test_cli_emits_green_and_residual(self):
        code, out, _, saved = self.run_cli(card("`true` → exit 0", "prosa"))
        self.assertEqual(code, 2)
        self.assertTrue(out["invoke_llm"])
        self.assertEqual((out["green"], out["residual"]), (["true"], ["prosa"]))
        self.assertEqual(saved, out)

    def test_cli_and_validate_share_decision(self):
        for crit in (["`false` → exit 0"], ["`true` → exit 0"], ["prosa"],
                     ["`true` → exit 0", "validator: llm"]):
            _, out, _, _ = self.run_cli(card(*crit))
            r = checks.validate(card(*crit), Spy(), REPO, config=TestTwoLevels.CFG)
            self.assertEqual((out["action"], out["invoke_llm"]),
                             (r["action"], r["invoke_llm"]), crit)

    def test_invalid_model_exit_3(self):
        code, out, err, _ = self.run_cli(card("`true` → exit 0"), {"model": "gpt"})
        self.assertEqual(code, 3)
        self.assertIsNone(out)
        self.assertIn("gpt", err)
        self.assertNotIn("Traceback", err)


def scoped_card(allowed, *crit):
    return ("# T\n## Obiettivo\nx\n## Puoi modificare\n" + "".join("- %s\n" % a for a in allowed)
            + "## Criteri di accettazione\n" + "".join("- %s\n" % c for c in crit)
            + "## Fuori scope\n-\n")


class TestScope(unittest.TestCase):
    """Il livello 1 non puo' validare un nodo che scrive fuori scope."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.d, True)
        for args in (["init", "-q"], ["config", "user.email", "a@b"], ["config", "user.name", "t"]):
            subprocess.run(["git"] + args, cwd=self.d, check=True)
        for n in ("ok.py", "other.py"):
            with open(os.path.join(self.d, n), "w") as f:
                f.write("1\n")
        subprocess.run(["git", "add", "."], cwd=self.d, check=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=self.d, check=True)

    def write(self, name, text="2\n"):
        with open(os.path.join(self.d, name), "w") as f:
            f.write(text)

    def test_in_scope_unchanged(self):
        self.write("ok.py")
        self.write("new.py")  # non tracciato ma permesso
        c = scoped_card(["`ok.py`, `new.py`"], "`true` -> exit 0")
        r = checks.run_checks(c, self.d)
        self.assertEqual(r["outcome"], "pass")
        self.assertEqual(r["out_of_scope"], [])
        self.assertEqual(checks.decide(r), ("done", False))

    def test_out_of_scope_tracked_is_ambiguous_even_if_green(self):
        self.write("ok.py")
        self.write("other.py")
        r = checks.run_checks(scoped_card(["`ok.py`"], "`true` -> exit 0"), self.d)
        self.assertEqual(r["green"], ["true"])
        self.assertEqual(r["outcome"], "ambiguous")
        self.assertEqual(r["out_of_scope"], ["other.py"])
        self.assertTrue(any("other.py" in x for x in r["residual"]))
        self.assertEqual(checks.decide(r), ("llm", True))

    def test_out_of_scope_untracked_is_ambiguous(self):
        self.write("stray.py")
        r = checks.run_checks(scoped_card(["`ok.py`"], "`true` -> exit 0"), self.d)
        self.assertEqual(r["outcome"], "ambiguous")
        self.assertTrue(checks.decide(r)[1])

    def test_validate_calls_llm_on_stray_file(self):
        self.write("stray.py")
        spy = Spy("fail")
        r = checks.validate(scoped_card(["`ok.py`"], "`true` -> exit 0"), spy, self.d,
                            config={"model": "haiku", "timeout_s": 60})
        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(r["verdict"], "fail")

    def test_failing_command_stays_fail(self):
        self.write("stray.py")
        r = checks.run_checks(scoped_card(["`ok.py`"], "`false` -> exit 0"), self.d)
        self.assertEqual(r["outcome"], "fail")
        self.assertEqual(checks.decide(r), ("retry", False))

    def test_directory_entry_allows_children(self):
        os.makedirs(os.path.join(self.d, "sub"))
        self.write("sub/x.py")
        r = checks.run_checks(scoped_card(["`sub/`"], "`true` -> exit 0"), self.d)
        self.assertEqual(r["outcome"], "pass")

    def test_no_section_is_ambiguous_even_if_green(self):
        """Senza `## Puoi modificare` lo scope non e' verificabile: livello 2."""
        self.write("other.py")
        c = "# T\n## Obiettivo\nx\n## Criteri di accettazione\n- `true` -> exit 0\n"
        r = checks.run_checks(c, self.d)
        self.assertEqual(r["green"], ["true"])
        self.assertEqual(r["outcome"], "ambiguous")
        self.assertTrue(any(x.startswith("scope: non verificabile") for x in r["residual"]))
        self.assertEqual(checks.decide(r), ("llm", True))

    def test_not_a_git_repo_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as d:
            r = checks.run_checks(scoped_card(["`ok.py`"], "`true` -> exit 0"), d)
            self.assertEqual(r["outcome"], "ambiguous")
            self.assertTrue(checks.decide(r)[1])

    def git(self, *a):
        subprocess.run(["git"] + list(a), cwd=self.d, check=True, stdout=subprocess.DEVNULL)

    def test_committed_stray_file_invisible_without_base_visible_with_base(self):
        """Il nodo committa il proprio lavoro: contro HEAD il diff e' vuoto (limite
        dichiarato); con --base/base= il file fuori scope viene visto."""
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.d, stdout=subprocess.PIPE,
                              universal_newlines=True).stdout.strip()
        self.write("ok.py")
        self.write("stray.py")
        self.git("add", ".")
        self.git("commit", "-qm", "lavoro del nodo")
        c = scoped_card(["`ok.py`"], "`true` -> exit 0")
        self.assertEqual(checks.run_checks(c, self.d)["out_of_scope"], [])  # limite senza base
        r = checks.run_checks(c, self.d, base=base)
        self.assertEqual(r["out_of_scope"], ["stray.py"])
        self.assertEqual((r["outcome"], checks.decide(r)), ("ambiguous", ("llm", True)))

    def test_committed_in_scope_with_base_passes(self):
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.d, stdout=subprocess.PIPE,
                              universal_newlines=True).stdout.strip()
        self.write("ok.py")
        self.git("commit", "-qam", "lavoro del nodo")
        r = checks.run_checks(scoped_card(["`ok.py`"], "`true` -> exit 0"), self.d, base=base)
        self.assertEqual(r["outcome"], "pass")

    def test_invalid_base_is_ambiguous(self):
        r = checks.run_checks(scoped_card(["`ok.py`"], "`true` -> exit 0"), self.d, base="nonesiste")
        self.assertEqual(r["outcome"], "ambiguous")

    def test_cli_base_flag(self):
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.d, stdout=subprocess.PIPE,
                              universal_newlines=True).stdout.strip()
        self.write("stray.py")
        self.git("add", ".")
        self.git("commit", "-qm", "x")
        os.makedirs(os.path.join(self.d, ".sjck", "cards"))
        with open(os.path.join(self.d, ".sjck", "cards", "T1.md"), "w") as f:
            f.write(scoped_card(["`ok.py`"], "`true` -> exit 0"))
        run = lambda *x: subprocess.run([sys.executable, os.path.join(SCRIPTS, "checks.py"), "run", "T1",
                                         "--cwd", self.d] + list(x), stdout=subprocess.PIPE,
                                        universal_newlines=True)
        self.assertEqual(run().returncode, 0)
        p = run("--base", base)
        self.assertEqual(p.returncode, 2)
        self.assertEqual(json.loads(p.stdout)["out_of_scope"], ["stray.py"])

    def test_sjck_dir_ignored(self):
        os.makedirs(os.path.join(self.d, ".sjck", "out"))
        self.write(".sjck/out/T.json")
        r = checks.run_checks(scoped_card(["`ok.py`"], "`true` -> exit 0"), self.d)
        self.assertEqual(r["outcome"], "pass")


class TestMissingConfig(Hermetic):
    """Senza nessun file di configurazione il livello 1 funziona coi default."""

    def test_load_config_default(self):
        cfg = checks.load_config(tempfile.mkdtemp())
        self.assertIn(cfg["model"], checks.MODELS)
        self.assertGreater(cfg["timeout_s"], 0)


if __name__ == "__main__":
    unittest.main()
