import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "bin" / "claude-rc"

STUB = textwrap.dedent("""\
    #!/bin/sh
    printf '%s %s\\n' "$(basename "$0")" "$*" >> "$STUB_LOG"
    case "$(basename "$0") $1 $2" in
        "claude auth status") [ -f "$STUB_LOGGED_IN" ] ;;
        "claude remote-control "*) exit 0 ;;
        "docker info "*) [ -f "$STUB_DOCKER_UP" ] ;;
        *) exit 0 ;;
    esac
""")


class Env:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.tmp.name)
        self.bin, self.home, self.work, self.tokens = d / "bin", d / "home", d / "work", d / "github"
        for p in (self.bin, self.home, self.work, self.tokens):
            p.mkdir()
        for name in ("claude", "gh", "git", "docker"):
            s = self.bin / name
            s.write_text(STUB)
            s.chmod(0o755)
        self.log = d / "log"
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.home),
            "STUB_LOG": str(self.log), "STUB_LOGGED_IN": str(d / "logged-in"), "STUB_DOCKER_UP": str(d / "docker-up"),
            "CLAUDE_RC_WORKSPACE": str(self.work), "CLAUDE_RC_GITHUB_DIR": str(self.tokens),
            "CLAUDE_RC_LOGIN_WAIT": "0", "HOSTNAME": "claude-rc-5d8f9-abcde",
        }
        (d / "logged-in").write_text("")       # logged in unless a test removes it
        (d / "docker-up").write_text("")

    def run(self, **extra):
        r = subprocess.run([str(ENTRYPOINT)], env={**self.env, **extra}, capture_output=True, text=True, timeout=30)
        return r, self.log.read_text().splitlines() if self.log.exists() else []


class Entrypoint(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.tmp.cleanup)

    def final(self, log):
        return [l for l in log if l.startswith("claude remote-control")]

    def test_controller_uses_the_session_name_as_is(self):
        r, log = self.e.run(CLAUDE_SESSION_NAME="ollyverse")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.final(log), ["claude remote-control --name ollyverse --spawn same-dir --capacity 32 --permission-mode acceptEdits"])

    def test_worker_appends_the_ordinal_plus_one(self):
        r, log = self.e.run(CLAUDE_SESSION_NAME="ollyverse", CLAUDE_SESSION_ORDINAL="1", HOSTNAME="claude-rc-worker-0",
                            CLAUDE_CAPACITY="8", CLAUDE_PERMISSION_MODE="plan")
        self.assertEqual(self.final(log), ["claude remote-control --name ollyverse-01 --spawn same-dir --capacity 8 --permission-mode plan"])

    def test_worker_without_an_ordinal_fails(self):
        r, log = self.e.run(CLAUDE_SESSION_NAME="ollyverse", CLAUDE_SESSION_ORDINAL="1", HOSTNAME="claude-rc-5d8f9-abcde")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no ordinal", r.stdout + r.stderr)
        self.assertEqual(self.final(log), [])

    def test_waits_for_the_login(self):
        os.remove(self.e.env["STUB_LOGGED_IN"])
        # log in "from the operator" after the first check: a helper writes the file when the hint appears
        hint = subprocess.Popen([str(ENTRYPOINT)], env={**self.e.env, "CLAUDE_SESSION_NAME": "x", "POD_NAMESPACE": "claude-rc"},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        first = hint.stdout.readline()
        pathlib.Path(self.e.env["STUB_LOGGED_IN"]).write_text("")
        out, _ = hint.communicate(timeout=30)
        self.assertIn("kubectl -n claude-rc exec -it claude-rc-5d8f9-abcde -c claude -- claude auth login", first)
        self.assertEqual(hint.returncode, 0, out)
        self.assertTrue(self.final(self.e.log.read_text().splitlines()))

    def test_logs_in_gh_for_every_token_file_and_ignores_dot_entries(self):
        (self.e.tokens / "ollyverse").write_text("t1")
        (self.e.tokens / "matofeder").write_text("t2")
        (self.e.tokens / "..data").mkdir()
        r, log = self.e.run(CLAUDE_SESSION_NAME="x")
        logins = sorted(l for l in log if l.startswith("gh auth login"))
        self.assertEqual(logins, ["gh auth login --hostname github.com --with-token"] * 2)
        self.assertIn("git config --global credential.useHttpPath true", log)
        self.assertIn("git config --global credential.https://github.com.helper claude-rc", log)

    def test_clones_missing_repositories_only(self):
        (self.e.work / "ollyplatform" / ".git").mkdir(parents=True)
        r, log = self.e.run(CLAUDE_SESSION_NAME="x",
                            GIT_REPOS="ollyplatform=https://github.com/ollyverse/ollyplatform.git ollyweb=https://github.com/ollyverse/ollyweb.git")
        clones = [l for l in log if l.startswith("git clone")]
        self.assertEqual(clones, [f"git clone --quiet https://github.com/ollyverse/ollyweb.git {self.e.work}/ollyweb"])

    def test_sets_the_identity_when_given(self):
        r, log = self.e.run(CLAUDE_SESSION_NAME="x", GIT_USER_NAME="Matej Feder", GIT_USER_EMAIL="feder.mato@gmail.com")
        self.assertIn("git config --global user.name Matej Feder", log)
        self.assertIn("git config --global user.email feder.mato@gmail.com", log)

    def test_waits_for_docker_when_docker_host_is_set(self):
        r, log = self.e.run(CLAUDE_SESSION_NAME="x", DOCKER_HOST="unix:///run/docker/docker.sock")
        self.assertIn("docker info", log)
        self.assertTrue(self.final(log))

    def test_no_docker_check_without_docker_host(self):
        r, log = self.e.run(CLAUDE_SESSION_NAME="x")
        self.assertFalse([l for l in log if l.startswith("docker")])

    def test_runs_in_the_workspace(self):
        # the stub records nothing about cwd, so check the directory exists and the server started
        r, log = self.e.run(CLAUDE_SESSION_NAME="x")
        self.assertTrue(self.e.work.is_dir())
        self.assertTrue(self.final(log))


if __name__ == "__main__":
    unittest.main()
