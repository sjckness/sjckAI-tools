"""P3 — validatori a due livelli: prima i controlli deterministici, l'LLM solo se serve."""
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
import precheck  # noqa: E402

PY = '"%s"' % sys.executable


def card(criteri, allowed="- `src/a.py`"):
    return """# T01 — nodo
## Obiettivo
Fare la cosa.
## Puoi modificare
%s
## Leggi
- `src/a.py`
## Criteri di accettazione
%s
## Fuori scope
- Altro
""" % (allowed, criteri)


class PrecheckTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sjck-pre-")
        for d in ("cards", "out"):
            os.makedirs(os.path.join(self.root, ".sjck", d))
        self.env = dict(os.environ)
        self.home = tempfile.mkdtemp(prefix="sjck-home-")
        os.environ["HOME"] = self.home
        for k in ("SJCK_CONFIG", "SJCK_VALIDATOR_MODEL", "SJCK_VALIDATOR_EFFORT"):
            os.environ.pop(k, None)
        self._out({"id": "T01", "status": "done", "changed": ["src/a.py"], "summary": "fatto"})

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def _card(self, text, nid="T01"):
        with open(os.path.join(self.root, ".sjck", "cards", nid + ".md"), "w", encoding="utf-8") as f:
            f.write(text)

    def _out(self, obj, nid="T01"):
        with open(os.path.join(self.root, ".sjck", "out", nid + ".json"), "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def _state(self, state):
        with open(os.path.join(self.root, ".sjck", "state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f)

    def _conf(self, obj, where=None):
        p = where or os.path.join(self.root, ".sjck", "config.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f)

    def _cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = precheck.main(["--cwd", self.root, "--id", "T01"] + list(argv))
        return code, buf.getvalue()

    # ---- il caso che deve risparmiare: fallimento deterministico, nessun LLM

    def test_failed_deterministic_check_means_no_llm_validator_call(self):
        self._card(card("- `%s -c \"import sys; sys.exit(3)\"` esce 0" % PY))
        code, out = self._cli()
        res = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(res["verdict"], "fail")
        self.assertFalse(res["llm_validator"], "nessuna chiamata al validatore LLM")
        self.assertEqual(res["reason"], "controllo deterministico fallito")
        self.assertIn("exit 3", res["findings"][0])
        # il findings e' azionabile: comando e criterio ci sono
        self.assertIn("esce 0", res["findings"][0])
        with open(os.path.join(self.root, ".sjck", "out", "T01.pre.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["verdict"], "fail")

    def test_all_commands_green_means_no_llm_validator_call(self):
        self._card(card("- `%s -c \"pass\"` esce 0\n- `%s -V` stampa la versione" % (PY, PY)))
        code, out = self._cli()
        res = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(res["verdict"], "pass")
        self.assertFalse(res["llm_validator"])
        self.assertEqual(res["commands"], 2)
        self.assertEqual([c["ok"] for c in res["checks"]], [True, True, True])

    def test_non_executable_criterion_escalates_to_the_llm(self):
        self._card(card("- `%s -c \"pass\"` esce 0\n- il diff non lascia TODO" % PY))
        code, out = self._cli()
        res = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(res["verdict"], "unclear")
        self.assertTrue(res["llm_validator"])
        self.assertEqual(res["llm_criteria"], ["il diff non lascia TODO"])
        self.assertTrue(res["checks"][1]["ok"], "il comando e' stato eseguito comunque")

    def test_card_with_no_command_escalates(self):
        self._card(card("- il diff aggiunge il campo `cost_usd`"))
        code, out = self._cli()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["reason"], "criteri non eseguibili: 1")
        # criteri vuoti: nemmeno un criterio da valutare -> comunque livello 2
        self._card(card(""))
        code, out = self._cli()
        self.assertEqual(code, 2)
        self.assertIn("nessun comando", json.loads(out)["reason"])

    def test_card_can_require_the_llm_validator(self):
        self._card(card("- `%s -c \"pass\"` esce 0, poi validator: llm sul diff" % PY))
        code, out = self._cli()
        self.assertEqual(code, 2)
        self.assertTrue(json.loads(out)["llm_validator"])

    def test_always_llm_in_config_keeps_the_second_level(self):
        self._card(card("- `%s -c \"pass\"` esce 0" % PY))
        self._conf({"validator": {"always_llm": True}})
        code, out = self._cli()
        self.assertEqual(code, 2)
        res = json.loads(out)
        self.assertTrue(res["llm_validator"])
        self.assertIn("configurazione", res["reason"])

    # ---- scope: deterministico anche questo

    def test_scope_violation_fails_without_the_llm(self):
        self._card(card("- `%s -c \"pass\"` esce 0" % PY))
        self._out({"id": "T01", "changed": ["src/a.py", "altro/b.py"]})
        code, out = self._cli()
        res = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(res["llm_validator"])
        self.assertIn("altro/b.py", res["findings"][0])

    def test_watchdog_writes_outside_card_fail_the_scope(self):
        self._card(card("- `%s -c \"pass\"` esce 0" % PY))
        self._state({"nodes": [{"id": "T01", "usage": {"writes_outside_card": 2}}]})
        code, out = self._cli()
        self.assertEqual(code, 1)
        self.assertIn("watchdog: 2 scritture fuori card", json.loads(out)["findings"][0])

    def test_directory_entry_covers_its_files(self):
        self._card(card("- `%s -c \"pass\"` esce 0" % PY, allowed="- `src/`"))
        self._out({"id": "T01", "changed": ["src/deep/c.py"]})
        self.assertEqual(self._cli()[0], 0)

    def test_missing_out_json_escalates_instead_of_failing(self):
        self._card(card("- `%s -c \"pass\"` esce 0" % PY))
        os.remove(os.path.join(self.root, ".sjck", "out", "T01.json"))
        code, out = self._cli()
        res = json.loads(out)
        self.assertEqual(code, 2)
        self.assertTrue(res["llm_validator"])
        self.assertIsNone(res["checks"][0]["ok"])

    # ---- modello configurabile

    def test_validator_model_is_configurable_and_can_be_smaller(self):
        self._card(card("- `%s -c \"pass\"` esce 0\n- giudizio sul diff" % PY))
        res = json.loads(self._cli()[1])
        self.assertEqual((res["llm_validator_model"], res["llm_validator_effort"]), ("sonnet", "high"),
                         "default = frontmatter dell'agente")
        self._conf({"validator": {"model": "haiku", "effort": "low"}})
        res = json.loads(self._cli()[1])
        self.assertEqual((res["llm_validator_model"], res["llm_validator_effort"]), ("haiku", "low"))
        # l'utente puo' metterlo in ~/.sjck/config.json, il progetto vince
        self._conf({"validator": {"model": "opus"}}, where=os.path.join(self.home, ".sjck", "config.json"))
        self.assertEqual(json.loads(self._cli()[1])["llm_validator_model"], "haiku")
        # e l'env vince su tutto
        os.environ["SJCK_VALIDATOR_MODEL"] = "fable"
        self.assertEqual(json.loads(self._cli()[1])["llm_validator_model"], "fable")

    def test_config_defaults_and_sources(self):
        self.assertEqual(config.load_config(self.root)["validator"]["model"], "sonnet")
        self._conf({"validator": {"model": "haiku"}})
        c = config.load_config(self.root)
        self.assertEqual(c["validator"]["model"], "haiku")
        self.assertEqual(c["validator"]["effort"], "high", "campo non toccato")
        self.assertTrue(any("config.json" in s for s in c["sources"]))

    # ---- robustezza

    def test_timeout_escalates_instead_of_failing(self):
        self._card(card("- `%s -c \"import time; time.sleep(30)\"` esce 0" % PY))
        code, out = self._cli("--timeout", "1")
        res = json.loads(out)
        self.assertEqual(code, 2, "un comando appeso non condanna il nodo: decide l'LLM")
        self.assertTrue(res["checks"][1]["timeout"])

    def test_unknown_runner_is_never_executed(self):
        self._card(card("- `rm -rf /` non deve girare"))
        code, out = self._cli()
        self.assertEqual(code, 2)
        res = json.loads(out)
        self.assertEqual(res["commands"], 0)
        self.assertEqual(res["llm_criteria"], ["`rm -rf /` non deve girare"])

    def test_extra_runner_can_be_allowed_by_config(self):
        self._card(card("- `mioscript --check` esce 0"))
        self._conf({"validator": {"commands_allow": ["mioscript"]}})
        res = json.loads(self._cli()[1])
        self.assertEqual(res["commands"], 1)
        self.assertEqual(res["verdict"], "fail", "comando inesistente: non eseguibile")

    def test_dry_run_lists_commands_without_running_them(self):
        marker = os.path.join(self.root, "marker.txt")
        self._card(card("- `%s -c \"open(r'%s','w').write('x')\"` esce 0"
                        % (PY, marker.replace("\\", "/"))))
        code, out = self._cli("--dry-run")
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(marker))
        self.assertTrue(json.loads(out)["checks"][1]["dry_run"])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".sjck", "out", "T01.pre.json")))

    def test_missing_card_or_run_is_an_error(self):
        self.assertEqual(self._cli()[0], 3)
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        self.assertEqual(precheck.main(["--cwd", empty, "--id", "T01"]), 3)


if __name__ == "__main__":
    unittest.main()
