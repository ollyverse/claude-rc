import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin" / "git-credential-claude-rc"


def run(stdin, tokens, action="get"):
    with tempfile.TemporaryDirectory() as d:
        for name, value in tokens.items():
            p = pathlib.Path(d) / name
            if value is None:
                p.mkdir()                       # a directory entry, like the Secret mount's ..data
            else:
                p.write_text(value)
        env = {**os.environ, "CLAUDE_RC_GITHUB_DIR": d}
        r = subprocess.run([str(HELPER), action], input=stdin, capture_output=True, text=True, env=env)
    return r


class Helper(unittest.TestCase):
    def test_owner_file_gives_the_token(self):
        r = run("protocol=https\nhost=github.com\npath=ollyverse/ollyplatform.git\n\n", {"ollyverse": "ghp_a\n"})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "username=x-access-token\npassword=ghp_a\n")

    def test_first_path_segment_is_the_owner(self):
        r = run("host=github.com\npath=matofeder/x/y\n\n", {"matofeder": "t"})
        self.assertEqual(r.stdout, "username=x-access-token\npassword=t\n")

    def test_unknown_owner_prints_nothing(self):
        r = run("host=github.com\npath=someone/repo\n\n", {"ollyverse": "t"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_other_host_prints_nothing(self):
        r = run("host=gitlab.com\npath=ollyverse/repo\n\n", {"ollyverse": "t"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_no_path_prints_nothing(self):
        r = run("host=github.com\n\n", {"ollyverse": "t"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_directory_entry_is_not_a_token(self):
        r = run("host=github.com\npath=..data/repo\n\n", {"..data": None})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_owner_with_odd_characters_is_refused(self):
        r = run("host=github.com\npath=../etc/repo\n\n", {"ollyverse": "t"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_store_and_erase_are_ignored(self):
        for action in ("store", "erase"):
            r = run("host=github.com\npath=ollyverse/repo\n\n", {"ollyverse": "t"}, action)
            self.assertEqual((r.returncode, r.stdout), (0, ""), action)


if __name__ == "__main__":
    unittest.main()
