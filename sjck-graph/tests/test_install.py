import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest


def find_root():
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(os.path.join(d, "install.sh")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RuntimeError("install.sh non trovato")
        d = parent


ROOT = find_root()
INSTALL = os.path.join(ROOT, "install.sh")


class TestInstall(unittest.TestCase):
    def setUp(self):
        if not shutil.which("bash") or not shutil.which("tar"):
            self.skipTest("bash o tar mancanti")
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.proj = os.path.join(self.tmp, "proj")
        os.makedirs(self.proj)
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.tgz = os.path.join(self.tmp, "fake.tar.gz")
        curl = os.path.join(self.bin, "curl")
        with open(curl, "w") as f:
            f.write('#!/bin/sh\nexec cat "$FAKE_TGZ"\n')
        os.chmod(curl, 0o755)

    def make_tgz(self, pycache):
        files = {
            "agents/a.md": "agent\n",
            "commands/c.md": "cmd\n",
            "skills/s/SKILL.md": "run ${CLAUDE_PLUGIN_ROOT}/scripts/x.py\n",
            "scripts/x.py": "print(1)\n",
            "scripts/prices.json": "{}\n",
        }
        if pycache:
            files["scripts/__pycache__/x.cpython-39.pyc"] = "junk"
        with tarfile.open(self.tgz, "w:gz") as tf:
            for rel, text in files.items():
                data = text.encode()
                ti = tarfile.TarInfo("sjck-main/sjck-graph/" + rel)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))

    def install(self):
        env = dict(os.environ)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["HOME"] = self.tmp
        env["FAKE_TGZ"] = self.tgz
        return subprocess.run(["bash", INSTALL], cwd=self.proj, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True)

    def baks(self):
        out = []
        for d, _, fs in os.walk(os.path.join(self.proj, ".claude")):
            out += [os.path.join(d, f) for f in fs if f.endswith(".bak")]
        return out

    def test_skips_subdirs(self):
        self.make_tgz(True)
        p = self.install()
        self.assertEqual(p.returncode, 0, p.stdout)
        sd = os.path.join(self.proj, ".claude", "sjck-scripts")
        self.assertTrue(os.path.isfile(os.path.join(sd, "x.py")))
        for d, dirs, _ in os.walk(sd):
            self.assertNotIn("__pycache__", dirs)
        with open(os.path.join(self.proj, ".claude", "skills", "s", "SKILL.md")) as f:
            txt = f.read()
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", txt)
        self.assertIn("/.claude/sjck-scripts/x.py", txt)
        self.assertTrue(any(w.endswith("/.claude/sjck-scripts/x.py") for w in txt.split()), txt)
        self.assertTrue(os.path.isabs(txt.split()[1]), txt)

    def test_copies_the_price_list_next_to_the_scripts(self):
        """config.py cerca prices.json accanto a se stesso: va copiato con gli script."""
        self.make_tgz(False)
        p = self.install()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertTrue(os.path.isfile(os.path.join(self.proj, ".claude", "sjck-scripts", "prices.json")))

    def test_reinstall_no_bak(self):
        self.make_tgz(False)
        self.assertEqual(self.install().returncode, 0)
        p = self.install()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.baks(), [])
        a = os.path.join(self.proj, ".claude", "agents", "a.md")
        with open(a, "w") as f:
            f.write("modificato\n")
        p = self.install()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(self.baks(), [a + ".bak"])

    def test_echo_graph_eval(self):
        self.make_tgz(False)
        p = self.install()
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn("/sjck-eval", p.stdout)

    def test_gitignore(self):
        with open(os.path.join(ROOT, ".gitignore")) as f:
            lines = f.read().splitlines()
        self.assertIn("__pycache__/", lines)
        self.assertIn("evals/results/", lines)


if __name__ == "__main__":
    unittest.main()
