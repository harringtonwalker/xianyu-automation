# Xianyu Automation Verification Report

Date: 2026-07-30
Risk: L3
Implementation: public-source candidate in `xianyu-automation/`; runtime data excluded

## Current truth

- Implemented locally: control console, SQLite workflow, authorized-source validation, source revisions, deterministic content, optional gated provider, three-image watermark renderer, full-content review hash, approval queue, lease/recovery/reconciliation, receipt states, Chrome MV3 extension, bound-owner Taobao/Xianyu extraction, startup/backup/restore/verification scripts, and operator guide.
- Live platform evidence: current logged-in `https://www.goofish.com/publish` contract matched after accounting for the intentionally hidden native file input.
- Live reversible raw-contract path: description, price, original price, and `无需邮寄` were filled and read back on the real page without clicking Publish; the page was reloaded and verified blank afterward. This was a contract probe, not a packaged-extension execution claim.
- Packaged-extension evidence: the unpacked extension was installed from a stable local path, paired with the loopback service, and returned a successful live semantic preflight with base signature `5dd2c232`.
- External truth: no listing is claimed as published by this acceptance evidence, no CAPTCHA bypass was attempted, no paid provider was called, and the publisher remained disabled outside explicitly approved execution.

## Automated verification

Command:

```bash
cd /path/to/xianyu-automation
./scripts/verify.command
```

Result:

- Python unittest: 59 passed, including 18 Git automation and publication-boundary failure-path tests
- Node test: 20 passed across core/contract and upload-runtime suites
- Python compileall: passed
- Node syntax checks for extension and dashboard: passed
- Manifest permission audit: no `cookies`, `debugger`, or stealth permission/setting
- Independent Reviewer and Tester: final PASS; P0/P1/P2 = 0 in the local and read-only tested scope

Covered:

- rights confirmation and authorized-source validation
- finite price/original-price rules, explicit delivery, default-location boundary, and forbidden unsupported claims
- mandatory stable external ID, full normalized-source fingerprint, current-version duplicate skipping, price/original-price/delivery/shipping/notes revisions, A→B→A historical rollback reactivation, and active-update blocking
- content generation and watermark image dimensions
- complete source/copy/image-byte review hash before approval
- exclusive global lease, attempt count, exhausted-attempt reset, and non-mutating extension ping
- pre-submit expired-lease recovery
- no automatic retry after submission begins; every blocked state forces the global publisher off
- strict RUNNING → AWAITING_RECEIPT → PUBLISHED ordering, unique receipt item IDs, HTTPS host/path/query/item-ID validation, and exact title/numeric-price matching
- manual published/not-published reconciliation
- risk-signal, semantic price/original-price/postage anchors, exact contract signatures, blank-form check, and DOM-drift blocking
- hidden native upload input support; native files alone are insufficient—three new previews, no progress/error state, and three stable polls are required
- persistent local execution/receipt association across browser restarts
- Xianyu owner-user-ID binding, exact item hostname/path validation, and competitor/arbitrary item-page extraction rejection
- malicious Origin and Host rejection; stale private-key migration
- private backup permissions, SHA-256 manifest, restore drill/migration check, exact Pillow runtime check, in-process rotating HTTP logs whose rollover files stay 600, startup stream rotation, and LaunchAgent syntax
- runtime data/assets directories are 700; SQLite/config/generated PNGs (plus WAL/SHM when present) are 600 even when the server is started directly
- publisher disabled by default
- numeric non-finite input rejection and explicit per-batch delivery requirement

## Running service checks

- `GET /api/health`: HTTP 200, `publisher_enabled=false`
- sample CSV import: 1 imported
- repeat sample CSV import: 0 imported, 1 duplicate skipped
- generation: 1 task moved to `PENDING_APPROVAL`
- output: three PNG images, each 1080×1080 and approximately 132 KB
- dashboard loaded in Chrome with all images and correct state
- malicious-origin CSV write: HTTP 403
- malicious-origin pairing-token GET: response has no `Access-Control-Allow-Origin`
- forged Host pairing-token GET: HTTP 421
- extension state-changing API without pairing token: HTTP 401
- paired extension ping: HTTP 200 and no job lease
- local sample full-content review: HTTP 200; job remained `PENDING_APPROVAL`
- backup `20260728-161916`: checksum verification, SQLite integrity, current migration, config parse, and permission checks passed in `--check-only`; live data was not changed

## Live Xianyu contract

Observed controls:

- one native multi-file input; visual input itself is hidden behind the upload card
- one visible contenteditable description editor
- two visible price inputs before delivery-specific controls
- delivery labels: 包邮 / 按距离计费 / 一口价 / 无需邮寄
- one visible Publish button
- no risk signal in visible page text
- the otherwise blank form currently preselects `包邮`; the adapter treats this as a platform default, then overwrites and reads back the reviewed delivery value
- the blank upload region has exactly one verified “添加首图” icon, pinned to the observed public asset fragment `O1CN016XczIR1iimNeEcZoh_`; `支持自提` is off; the non-empty account-default location is semantically anchored

Raw live semantic contract: pass. The original page was also reversibly filled/read back and then cleared without clicking Publish.

Current adapter signatures derived from the observed fields and semantic labels:

- base: `5dd2c232`
- flat shipping control visible: `7eeb481c`

The packaged extension completed the current signature preflight in the verified environment. The adapter will not lease a job without this check; its captured upload baseline, verified blank icon, self-pickup state, location, signature, and timestamp expire after 24 hours and must match the fresh execution tab. Freshness is checked again immediately before entering the submitting state.

Machine-readable retained evidence: `docs/live-contract.json`.

## Human-gated remaining acceptance

1. Import an owned or explicitly authorized real product and select its verified delivery mode.
2. Inspect and mark reviewed the complete product facts, full generated copy, prices, delivery, and all watermarked images.
3. Refresh the packaged extension semantic preflight if the 24-hour contract has expired.
4. Explicitly approve the bounded batch and enable the publisher switch.
5. Allow the authorized real Publish action.
6. Verify the resulting strict `goofish.com/item` URL, item ID, exact title, numeric price, visible content, and account inventory.

Until those account-side steps are completed, the correct state is “the local production system, packaged extension, pairing, and live preflight are verified; real listing and receipt acceptance remain an explicit operator gate.”
