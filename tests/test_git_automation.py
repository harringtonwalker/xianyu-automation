from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(
    command: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class GitAutomationTests(unittest.TestCase):
    def make_repo(self) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="xianyu-git-automation-"))
        self.addCleanup(shutil.rmtree, directory, True)
        self.assertEqual(run(["git", "init", "-q"], cwd=directory).returncode, 0)
        return directory

    def copy_boundary_script(self, repo: Path) -> Path:
        destination = repo / "scripts" / "check-publication-boundary.command"
        destination.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / destination.name, destination)
        destination.chmod(0o755)
        return destination

    def test_publication_boundary_accepts_safe_utf8_source(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        (repo / "README.md").write_text("# Safe source\n", encoding="utf-8")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Publication boundary: PASS", result.stdout)

    def test_publication_boundary_rejects_private_runtime_path(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        private_file = repo / "data" / "private.db"
        private_file.parent.mkdir(parents=True)
        private_file.write_bytes(b"not-a-real-database")
        self.assertEqual(run(["git", "add", "-f", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("data/private.db: private runtime directory", result.stderr)
        self.assertNotIn("not-a-real-database", result.stderr)

    def test_pre_push_rejects_main(self) -> None:
        repo = self.make_repo()
        hook = repo / "pre-push"
        shutil.copy2(ROOT / ".githooks" / "pre-push", hook)
        hook.chmod(0o755)
        update = "refs/heads/main abc refs/heads/main def\n"

        result = run([str(hook), "origin", "unused"], cwd=repo, input_text=update)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not allow local direct pushes to main", result.stderr)

    def test_pre_push_allows_codex_branch(self) -> None:
        repo = self.make_repo()
        hook = repo / "pre-push"
        shutil.copy2(ROOT / ".githooks" / "pre-push", hook)
        hook.chmod(0o755)
        update = "refs/heads/codex/docs abc refs/heads/codex/docs def\n"

        result = run([str(hook), "origin", "unused"], cwd=repo, input_text=update)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_publish_script_creates_draft_and_never_merges(self) -> None:
        content = (ROOT / "scripts" / "publish-pr.command").read_text(encoding="utf-8")

        self.assertIn("--draft", content)
        self.assertIn("--base main", content)
        self.assertNotIn("gh pr merge", content)
        self.assertNotIn("--auto", content)


if __name__ == "__main__":
    unittest.main()
