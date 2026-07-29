# Changelog

All notable changes to this project are documented here.

## [1.0.2] - 2026-07-30

### Security

- Return the server-owned loopback origin value instead of reflecting the matching request header into CORS responses.

## [1.0.1] - 2026-07-30

### Security

- Upgrade Pillow to 12.3.0 to resolve current upstream security advisories;
- stop reflecting Chrome extension origins into CORS response headers;
- validate extension write origins with the exact Chrome extension ID format;
- replace a test-only URL substring assertion with an exact permission allowlist.

## [1.0.0] - 2026-07-30

### Added

- Local Python control plane and SQLite workflow state machine;
- authorized-source validation, stable product identity, revisions and deduplication;
- deterministic fact-bound copy generation with an explicitly gated optional model provider;
- three 1080×1080 branded watermark images;
- full-content review hash and approval queue;
- least-privilege Chrome Manifest V3 extension;
- semantic Xianyu publish-page preflight, upload evidence and fail-closed circuit breaker;
- strict item receipt verification and manual reconciliation;
- backup, restore, verification and optional macOS login-service scripts;
- bilingual documentation, machine-readable `llms.txt`, CI and security policy.

### Verified

- 41 Python tests and 20 Node.js tests;
- real logged-in publish-page read-only/reversible contract;
- packaged extension installation, local pairing and semantic preflight;
- no real listing is claimed as published by this repository's acceptance evidence.
