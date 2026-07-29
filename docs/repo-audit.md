# Xianyu Automation Candidate Audit

Audit date: 2026-07-28

## Scope

Five public repositories were shallow-cloned into an isolated temporary directory. The audit covered the first-party file tree, runtime entrypoints, dependencies and lockfiles where present, browser-control code, tests, license/security material, release/commit activity, and the Xianyu publish path. Generated assets, binary artifacts, vendored dependencies, and target-irrelevant examples were excluded.

Pinned audit inputs:

| Repository | Audited HEAD |
|---|---|
| `https://github.com/jackwener/OpenCLI.git` | `5256711a25458e537c5a63d2a6f9c7fd36d0d1eb` |
| `https://github.com/timmyagentic/xianyu-seller-agent.git` | `3fa311fa57ea5d474cb207220f55d5513cd3c824` |
| `https://github.com/tianyiiiii111/xianyu-rpa.git` | `84f94c12e6d8fe1736ea986ea6f8133d798f1cd0` |
| `https://github.com/SunKaiY/xianyu-publisher.git` | `2ce0f0ebe89142e2a1b2fe1924ada179fd0da56d` |
| `https://github.com/smartcat999/xianyu-publish.git` | `d117c84ea42dad9df972581b53e8ba4a6a54eabc` |

Reproduction boundary: the isolated clones were deliberately not copied into this delivery, avoiding redistribution or accidental adoption. Each snapshot can be reconstructed with `git init`, `git remote add origin <URL>`, `git fetch --depth 1 origin <SHA>`, and `git checkout --detach FETCH_HEAD`. The HEAD pins were refreshed with `git ls-remote <URL> HEAD` on the audit date.

## Findings

### jackwener/OpenCLI

- Source: `https://github.com/jackwener/OpenCLI`
- Decision: `reference-only`
- Strengths: Apache-2.0 license, current maintenance, CI/tests, explicit security/privacy documentation, input validation, and fail-closed result reporting.
- Gaps: Xianyu publish tests are synthetic JSDOM tests rather than live end-to-end evidence. The adapter assumes title/category/condition controls that are absent from the current live ordinary-seller publish page. The general extension requests capabilities broader than this task needs.
- Reusable idea: validate inputs before touching the page and require positive success evidence.

### timmyagentic/xianyu-seller-agent

- Source: `https://github.com/timmyagentic/xianyu-seller-agent`
- Decision: `reference-only`
- Strengths: explicit workflow states, failure records, and a real-publish confirmation flag.
- Gaps: publication tests use a fake page, not current Xianyu. Runtime browser setup injects cookies and uses anti-detection/no-sandbox/disabled-web-security techniques. Its primary scope is reply, delivery, and relisting rather than this image/content pipeline. No clear repository license was found in the audited snapshot.
- Reusable idea: leases, structured failure, and receipt-oriented state.

### tianyiiiii111/xianyu-rpa

- Source: `https://github.com/tianyiiiii111/xianyu-rpa`
- Decision: `reject`
- Gaps: no production test suite or license; stealth browser plugin, raw cookie persistence, no-sandbox mode, competitor search scraping, human-delay simulation, and blind category retries. No durable queue, watermark engine, or receipt verification.

### SunKaiY/xianyu-publisher

- Source: `https://github.com/SunKaiY/xianyu-publisher`
- Decision: `reject`
- Gaps: Windows-only PyQt/Selenium application, automatic driver downloads, Chrome process termination, UA/browser spoofing, no tests/license, and no recovery/state/receipt layer.

### smartcat999/xianyu-publish

- Source: `https://github.com/smartcat999/xianyu-publish`
- Decision: `reference-only`
- Gaps: documentation-only OpenClaw skill, no executable implementation, tests, or license. Claimed operational limits are not backed by current platform evidence.

## Market tooling boundary

Commercial tools discovered during research advertise whole-site copying, watermark removal, account nurturing, anti-risk behavior, or batch RPA. These marketing claims are not auditable implementation evidence and several conflict with the rights, credential, and platform-control boundaries of this system.

## Final architecture choice

Build a local SQLite-backed control plane, deterministic/optional-provider content generator, Pillow watermark renderer, and a narrow Chrome MV3 extension. The extension uses the user's existing logged-in session but does not request Cookie or debugger privileges, spoof browser identity, or bypass risk controls. Page drift and risk prompts block the job and require review.
