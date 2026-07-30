## What changed

Describe the user-visible or operational change.

## Why

Explain the problem and the evidence behind the change.

## Safety and data boundary

- [ ] No Cookie export/injection, debugger permission, stealth, CAPTCHA bypass, competitor text/image copying, watermark removal, or access-control bypass.
- [ ] Any public competitor-metadata analysis remains isolated from the publication queue and includes rights, rate, retention, and failure boundaries.
- [ ] Human review, batch approval, fail-closed behavior, and strict receipt validation remain intact.
- [ ] No token, account ID, database, log, backup, generated asset, or private product/customer data is included.

## Verification

- [ ] `./scripts/verify.command`
- [ ] Relevant failure path tested
- [ ] Staged diff reviewed
