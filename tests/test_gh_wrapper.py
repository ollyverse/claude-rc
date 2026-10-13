"""bin/gh: runs the real gh with the token of the current repository's GitHub
owner in GH_TOKEN, for that one process only. A stub stands in for the real gh
(CLAUDE_RC_GH_BIN) and prints what it received."""
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "bin" / "gh"

STUB = textwrap.dedent("""\
    #!/bin/sh
    printf 'GH_TOKEN=%s args=%s\\n' "${GH_TOKEN:-<unset>}" "$*"
""")


class Env:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.tmp.name)
        self.stub, self.tokens, self.repo = d / "gh-real", d / "github", d / "repo"
        self.stub.write_text(STUB)
        self.stub.chmod(0o755)
        self.tokens.mkdir()
        (self.tokens / "ollyverse").write_text("tok-olly\n")
        (self.tokens / "matofeder").write_text("tok-mato")
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.env = {**os.environ, "CLAUDE_RC_GH_BIN": str(self.stub), "CLAUDE_RC_GITHUB_DIR": str(self.tokens)}
        self.env.pop("GH_TOKEN", None)

    def origin(self, url):
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", url], check=True)

    def run(self, *args, cwd=None, **extra):
        r = subprocess.run([str(WRAPPER), *args], cwd=cwd or self.repo, env={**self.env, **extra},
                           capture_output=True, text=True)
        return r.returncode, r.stdout.strip()


class Wrapper(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.tmp.cleanup)

    def test_https_origin_picks_the_owner_token(self):
        self.e.origin("https://github.com/matofeder/dmk.git")
        self.assertEqual(self.e.run("pr", "list"), (0, "GH_TOKEN=tok-mato args=pr list"))

    def test_ssh_origin_picks_the_owner_token_and_strips_the_newline(self):
        self.e.origin("git@github.com:ollyverse/ollyplatform.git")
        self.assertEqual(self.e.run("--version"), (0, "GH_TOKEN=tok-olly args=--version"))

    def test_unknown_owner_runs_without_a_token(self):
        self.e.origin("https://github.com/someone/repo.git")
        self.assertEqual(self.e.run("auth", "status"), (0, "GH_TOKEN=<unset> args=auth status"))

    def test_outside_a_repository_runs_without_a_token(self):
        self.assertEqual(self.e.run("--version", cwd=self.e.tmp.name), (0, "GH_TOKEN=<unset> args=--version"))

    def test_other_host_runs_without_a_token(self):
        self.e.origin("https://gitlab.com/ollyverse/repo.git")
        self.assertEqual(self.e.run("x"), (0, "GH_TOKEN=<unset> args=x"))

    def test_an_explicit_gh_token_wins(self):
        self.e.origin("https://github.com/matofeder/dmk.git")
        self.assertEqual(self.e.run("x", GH_TOKEN="mine"), (0, "GH_TOKEN=mine args=x"))

    def test_odd_owner_is_refused(self):
        self.e.origin("https://github.com/../etc/repo.git")
        self.assertEqual(self.e.run("x"), (0, "GH_TOKEN=<unset> args=x"))


if __name__ == "__main__":
    unittest.main()
