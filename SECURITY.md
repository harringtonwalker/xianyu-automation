# Security Policy

## Supported versions

Security fixes are applied to the latest `1.x` release and the default branch.

## Report a vulnerability

Please do not open a public issue for a vulnerability, leaked credential, or account-specific platform behavior.

Use GitHub's private vulnerability reporting:

https://github.com/harringtonwalker/xianyu-automation/security/advisories/new

Include:

- affected version or commit;
- the smallest reproducible path;
- security impact;
- whether the issue can expose pairing tokens, local product data, receipts, browser state, or publication actions;
- a proposed fix if available.

Never include real cookies, pairing tokens, API keys, account IDs, customer data, or unpublished product material.

## Security invariants

Changes must preserve these properties:

- the HTTP service binds to loopback by default;
- state-changing extension routes require the local pairing token;
- the browser extension does not request `cookies`, `debugger`, or broad Xianyu host permissions;
- arbitrary product pages and unbound owner profiles cannot become authorized sources;
- content and image bytes remain bound to the human review hash;
- no automatic retry occurs after submission begins without a verified receipt;
- CAPTCHA, risk prompts, DOM drift, and uncertain receipts fail closed and disable the global publisher;
- `data/`, `backups/`, logs, databases, generated assets, secrets, and account-specific values never enter Git.

## Scope

This policy covers the source in this repository. Platform policies, user accounts, locally installed extensions, third-party model providers, and modified forks remain the operator's responsibility.
