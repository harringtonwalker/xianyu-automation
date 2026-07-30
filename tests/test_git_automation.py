from __future__ import annotations

import os
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
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )


class GitAutomationTests(unittest.TestCase):
    def make_repo(self) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="xianyu-git-automation-"))
        self.addCleanup(shutil.rmtree, directory, True)
        self.assertEqual(run(["git", "init", "-q"], cwd=directory).returncode, 0)
        return directory

    def make_committed_repo(self, branch: str = "codex/test") -> Path:
        repo = self.make_repo()
        self.assertEqual(
            run(["git", "config", "user.email", "test@example.com"], cwd=repo).returncode,
            0,
        )
        self.assertEqual(
            run(["git", "config", "user.name", "Test User"], cwd=repo).returncode,
            0,
        )
        (repo / "README.md").write_text("# Test\n", encoding="utf-8")
        self.assertEqual(run(["git", "add", "README.md"], cwd=repo).returncode, 0)
        self.assertEqual(
            run(["git", "commit", "-q", "-m", "test fixture"], cwd=repo).returncode,
            0,
        )
        self.assertEqual(run(["git", "branch", "-M", branch], cwd=repo).returncode, 0)
        return repo

    def copy_boundary_script(self, repo: Path) -> Path:
        destination = repo / "scripts" / "check-publication-boundary.command"
        destination.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / destination.name, destination)
        destination.chmod(0o755)
        return destination

    def copy_publish_script(self, repo: Path) -> Path:
        destination = repo / "scripts" / "publish-pr.command"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / destination.name, destination)
        destination.chmod(0o755)
        return destination

    def fake_gh_env(
        self,
        repo: Path,
        pr_record: str = "",
        *,
        authenticated: bool = True,
    ) -> dict[str, str]:
        bin_dir = Path(tempfile.mkdtemp(prefix="xianyu-fake-gh-"))
        self.addCleanup(shutil.rmtree, bin_dir, True)
        gh = bin_dir / "gh"
        if "\t" in pr_record:
            pr_url, pr_is_draft = pr_record.split("\t", 1)
            pr_output = f"  printf '%s\\t%s\\n' '{pr_url}' '{pr_is_draft}'\n"
        else:
            pr_output = "  print -r -- ''\n"
        gh.write_text(
            "#!/bin/zsh\n"
            f"if [[ \"$1 $2\" == \"auth status\" ]]; then exit {0 if authenticated else 1}; fi\n"
            "if [[ \"$1 $2\" == \"pr list\" ]]; then\n"
            f"{pr_output}"
            "  exit 0\n"
            "fi\n"
            "exit 97\n",
            encoding="utf-8",
        )
        gh.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        return env

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

    def test_publication_boundary_rejects_nested_private_path(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        private_file = repo / "customer" / "data" / "items.json"
        private_file.parent.mkdir(parents=True)
        private_file.write_text('{"title":"private"}\n', encoding="utf-8")
        self.assertEqual(run(["git", "add", "-f", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("customer/data/items.json: private runtime directory", result.stderr)

    def test_publication_boundary_rejects_secret_config_name(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        (repo / ".npmrc").write_text("registry=https://example.invalid\n", encoding="utf-8")
        self.assertEqual(run(["git", "add", "-f", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".npmrc: private or generated file type", result.stderr)

    def test_publication_boundary_rejects_generic_credential_assignment(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        credential_text = "SERVICE_" + "TOKEN=realvalue1234567890\n"
        (repo / "settings.txt").write_text(credential_text, encoding="utf-8")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("settings.txt: credential assignment", result.stderr)
        self.assertNotIn("realvalue1234567890", result.stderr)

    def test_publication_boundary_rejects_lowercase_quoted_credential(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        credential_text = "api_" + 'key = "real-secret-value-123456"\n'
        (repo / "settings.py").write_text(credential_text, encoding="utf-8")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("settings.py: credential assignment", result.stderr)

    def test_publication_boundary_rejects_lowercase_unquoted_credential(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        credential_text = "service_" + "token: realSecretValue123456\n"
        (repo / "settings.yml").write_text(credential_text, encoding="utf-8")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("settings.yml: credential assignment", result.stderr)

    def test_publication_boundary_does_not_allow_placeholder_substrings(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        credential_text = "service_" + 'token = "contestSecretValue123456"\n'
        (repo / "settings.py").write_text(credential_text, encoding="utf-8")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("settings.py: credential assignment", result.stderr)

    def test_publication_boundary_allows_exact_placeholder_value(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        placeholder_text = "service_" + 'token = "placeholder"\n'
        (repo / "example.py").write_text(placeholder_text, encoding="utf-8")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_publication_boundary_rejects_unapproved_structured_data(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        (repo / "products.json").write_text('{"title":"private"}\n', encoding="utf-8")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "products.json: structured data file is not on the public allowlist",
            result.stderr,
        )

    def test_publication_boundary_rejects_binary_file(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        (repo / "asset.bin").write_bytes(b"binary\0data")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("asset.bin: binary file requires explicit human review", result.stderr)

    def test_publication_boundary_rejects_symlink(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        (repo / "target.txt").write_text("safe\n", encoding="utf-8")
        (repo / "linked.txt").symlink_to("target.txt")
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "linked.txt: symlinks and submodules are not public-source inputs",
            result.stderr,
        )

    def test_publication_boundary_rejects_submodule_entry(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        result = run(
            [
                "git",
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{('1' * 40)},vendor/module",
            ],
            cwd=repo,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "vendor/module: symlinks and submodules are not public-source inputs",
            result.stderr,
        )

    def test_publication_boundary_rejects_oversized_file(self) -> None:
        repo = self.make_repo()
        script = self.copy_boundary_script(repo)
        (repo / "oversized.txt").write_bytes(b"x" * (5 * 1024 * 1024 + 1))
        self.assertEqual(run(["git", "add", "."], cwd=repo).returncode, 0)

        result = run([str(script)], cwd=repo)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("oversized.txt: file exceeds the 5 MiB public-source limit", result.stderr)

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
        self.assertIn("printf '%s\\n'", content)
        self.assertNotIn("gh pr merge", content)
        self.assertNotIn("--auto", content)

    def test_publish_script_rejects_wrong_origin(self) -> None:
        repo = self.make_committed_repo()
        script = self.copy_publish_script(repo)
        self.assertEqual(
            run(["git", "remote", "add", "origin", "https://github.com/other/repo.git"], cwd=repo).returncode,
            0,
        )

        result = run([str(script)], cwd=repo, env=self.fake_gh_env(repo))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin is not harringtonwalker/xianyu-automation", result.stderr)

    def test_publish_script_rejects_expired_github_authentication(self) -> None:
        repo = self.make_committed_repo()
        script = self.copy_publish_script(repo)

        result = run(
            [str(script)],
            cwd=repo,
            env=self.fake_gh_env(repo, authenticated=False),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GitHub CLI is not authenticated", result.stderr)

    def test_publish_script_rejects_non_codex_branch(self) -> None:
        repo = self.make_committed_repo("feature/test")
        script = self.copy_publish_script(repo)
        self.assertEqual(
            run(
                [
                    "git",
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/harringtonwalker/xianyu-automation.git",
                ],
                cwd=repo,
            ).returncode,
            0,
        )

        result = run([str(script)], cwd=repo, env=self.fake_gh_env(repo))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Use a codex/<slug> branch", result.stderr)

    def test_publish_script_rejects_dirty_worktree(self) -> None:
        repo = self.make_committed_repo()
        script = self.copy_publish_script(repo)
        self.assertEqual(
            run(
                [
                    "git",
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/harringtonwalker/xianyu-automation.git",
                ],
                cwd=repo,
            ).returncode,
            0,
        )
        (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

        result = run([str(script)], cwd=repo, env=self.fake_gh_env(repo))

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worktree is not clean", result.stderr)

    def test_publish_script_refuses_existing_ready_for_review_pr(self) -> None:
        repo = self.make_committed_repo()
        script = self.copy_publish_script(repo)
        self.assertEqual(run(["git", "add", "scripts/publish-pr.command"], cwd=repo).returncode, 0)
        self.assertEqual(
            run(["git", "commit", "-q", "-m", "add publish script"], cwd=repo).returncode,
            0,
        )
        self.assertEqual(
            run(
                [
                    "git",
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/harringtonwalker/xianyu-automation.git",
                ],
                cwd=repo,
            ).returncode,
            0,
        )
        env = self.fake_gh_env(
            repo,
            "https://github.com/harringtonwalker/xianyu-automation/pull/9\tfalse",
        )

        result = run([str(script)], cwd=repo, env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existing PR is no longer a draft", result.stderr)

    def test_post_commit_skips_non_codex_branch(self) -> None:
        repo = self.make_committed_repo("main")
        hook = repo / "post-commit"
        shutil.copy2(ROOT / ".githooks" / "post-commit", hook)
        hook.chmod(0o755)

        result = run([str(hook)], cwd=repo)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_post_commit_skips_in_progress_git_operation(self) -> None:
        repo = self.make_committed_repo()
        hook = repo / "post-commit"
        shutil.copy2(ROOT / ".githooks" / "post-commit", hook)
        hook.chmod(0o755)
        (repo / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="ascii")

        result = run([str(hook)], cwd=repo)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped while a Git operation is in progress", result.stderr)

    def test_post_commit_propagates_publish_failure_with_recovery_hint(self) -> None:
        repo = self.make_committed_repo()
        hook = repo / "post-commit"
        shutil.copy2(ROOT / ".githooks" / "post-commit", hook)
        hook.chmod(0o755)
        publisher = repo / "scripts" / "publish-pr.command"
        publisher.parent.mkdir()
        publisher.write_text("#!/bin/zsh\nexit 7\n", encoding="utf-8")
        publisher.chmod(0o755)

        result = run([str(hook)], cwd=repo)

        self.assertEqual(result.returncode, 1)
        self.assertIn("automatic GitHub PR sync failed", result.stderr)
        self.assertIn("./scripts/publish-pr.command", result.stderr)


if __name__ == "__main__":
    unittest.main()
