# Codex repository instructions

This repository is the public source tree. The installed runtime, pairing token,
SQLite data, logs, backups, generated images, browser state, and private product
material are never part of a source-code change.

## Required GitHub workflow

For every intentional Codex change:

1. Start from a clean checkout with `./scripts/start-codex-change.command <slug>`.
2. Work only on the resulting `codex/<slug>` branch.
3. Stage only the intended files and inspect the staged diff.
4. Commit normally. The repository hooks run the full verification suite, reject
   unsafe public material, push the branch, and create or update a draft PR.
5. If the post-commit network step fails, keep the local commit and rerun
   `./scripts/publish-pr.command`.
6. Wait for GitHub CI and CodeQL. Never merge, enable auto-merge, or push `main`
   without Walker's current explicit approval.

Do not bypass hooks with `--no-verify`. Do not use a filesystem watcher or
automatically commit every saved file. A PR must represent a deliberate,
reviewable commit with a clean worktree.

Install or repair the local binding with:

```bash
./scripts/install-git-automation.command
```

Remove only the local binding with:

```bash
./scripts/uninstall-git-automation.command
```

## Product and rights boundary

- Publication uses only owned or explicitly authorized product facts and assets.
- Public competitor metadata may be proposed for bounded market intelligence:
  price ranges, categories, listing cadence, and recurring selling-point
  keywords. It must remain separated from the publication queue.
- Never copy competitor descriptions or images, remove watermarks, bypass login,
  CAPTCHA, rate limits, access controls, or platform risk controls, or present
  derived competitor material as the operator's own.
- Competitive-intelligence collection is not implemented merely because this
  boundary is documented. It requires a separate, evidence-backed feature PR.
- Human content review, bounded batch approval, fail-closed behavior, and strict
  publication receipts are non-negotiable.

## Verification

Run `./scripts/verify.command`. Any change to Git automation must also exercise:

- direct `main` push rejection;
- unsafe tracked-file rejection;
- clean-worktree enforcement;
- one real `codex/*` draft-PR path without automatic merge.
