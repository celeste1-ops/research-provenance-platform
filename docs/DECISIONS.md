# Decisions

Where the PRD and reality disagreed, or the PRD left a choice open, this file records
what was chosen and why (PRD §7 rule 7). Newest decisions are appended at the end of
each section.

## Environment

- **D-001 · Cloud build without FreeTSA / OpenTimestamps.** The cloud development
  environment's egress policy blocks `freetsa.org`, the OpenTimestamps calendars and the
  public block explorers (HTTP 403 from the proxy). As the PRD's §17 work rules allow,
  development and tests use `MockProvider`; tests that need the real services are marked
  `@pytest.mark.network` and only run with `make test-network` (`RPROV_NETWORK_TESTS=1`)
  on the Mac.
- **D-002 · Python 3.12 via uv.** The machine's default Python is 3.13; the project pins
  `requires-python = ">=3.12,<3.14"` and the lockfile is generated with 3.12, the PRD's
  version.
- **D-003 · Frontend toolchain versions.** TypeScript 7 (the native port) and Vite 8 had
  just been released; the UI pins TypeScript 5.9 and Vite 7 for stability. Exact
  versions are locked in `web/package-lock.json` (PRD S6).

## FreeTSA certificates (PRD §9, S6)

- **D-004 · Where the built-in FreeTSA certificates came from.** `freetsa.org` is not
  reachable from the cloud environment, so the certificates could not be downloaded from
  the source. The committed copies are:
  - `cacert.pem` (FreeTSA Root CA, valid 2016-03-13 → 2041-03-07, SHA-256 fingerprint
    `A6:37:9E:7C:EC:C0:5F:AA:3C:BF:07:60:13:D7:45:E3:27:BB:BA:A3:8C:0B:9A:F2:24:69:D4:70:1D:18:AA:BC`).
    Two unrelated npm packages (`parentsplit-verify`, `@truetake/verify-aul`) ship
    byte-identical copies.
  - `tsa.crt` (FreeTSA TSA certificate, valid 2016-03-13 → **2026-03-11**, SHA-256
    `46:94:BE:23:C3:A5:30:04:44:4B:17:05:BF:E5:A7:F5:0A:6D:2A:16:38:19:4F:23:C0:F3:89:B6:8B:D7:8A:75`),
    from the `rfc3161ng` 2.1.3 sdist on PyPI. Its signature verifies against the root above.

  That TSA certificate expired before today (2026-10-11), so FreeTSA is almost certainly
  signing with a newer one now. This does not break verification: every request sets
  `certReq=true`, so each `.tsr` carries the signing certificate, and only the root is a
  trust anchor. **On the Mac, run `make freetsa-certs` once**: it downloads both files from
  `https://freetsa.org/files/`, prints their fingerprints, and refuses to overwrite the root
  if its fingerprint differs from the one above. The `network` test for AC-09 checks a real
  FreeTSA response against the committed root.

## Records and verification

- **D-005 · Mock third-party timestamps are real RFC 3161 tokens.** `MockProvider("tsa")`
  signs genuine RFC 3161 responses with a throwaway CA committed under
  `core/provenance_core/providers/mock_tsa/` (private key included on purpose). Tests and
  cloud development therefore run the exact verification path FreeTSA tokens take, and
  `openssl ts -verify` accepts them. Nothing trusts the mock root unless asked to:
  the app trusts it only when `RPROV_TSA=mock`, `verify.py` only with `--tsa-root`.
  Mock Bitcoin anchors use a clearly marked format and are never shown as confirmed
  outside test mode.
- **D-006 · "No timestamp yet" is a warning in verification.** The PRD lists two warning
  cases (later-verified referenced record; the two proofs more than 24 h apart). A record
  with no verified proof at all passes every integrity check but has no time; reporting it
  as a plain "pass" would invite reading a time into it, so it is a warning
  (`NO_VERIFIED_TIME`) and no time is shown.
- **D-007 · Genesis payload is always disclosed.** The genesis payload holds the public
  key every signature is checked against, so evidence bundles always include it, whatever
  disclosure level the user picks for other records. The export preview says so.
- **D-008 · Relations must point from newer to older.** AC-12 asks for a 400 on relations
  pointing at a "later" record. For a new `entry` every existing record is earlier, so the
  rule bites on `link` records: `to` must have a smaller `seq` than `from` (PRD §8: "新记录
  rel 旧记录"). The verifier stays lenient (it only checks V7, refs earlier than the
  referencing record) so bundles from future versions keep verifying.
- **D-009 · Local clock time is shown with author statements.** The record's `local_time`
  comes from the author's computer and is unverified, so the detail view lists it under
  "Author statement" (marked "self-reported, unverified"), never under "Verified record".
- **D-010 · No-op later additions are refused.** Setting a milestone that is already set,
  withdrawing a relation that is not active, adding an active relation twice, or retracting
  an entry twice returns 400 instead of appending a meaningless record.

## Local app

- **D-011 · Key storage outside macOS.** The signing key lives in the macOS Keychain via
  `keyring` (PRD S5). Linux containers have no keychain, so for development only there is
  an opt-in `RPROV_KEYSTORE=dev-insecure-file` (a 0600 file in the data directory, with a
  warning in the log). It is never the default; tests use an in-memory keystore.
- **D-012 · One process-wide write lock.** All write transactions (records, time proofs,
  metadata) run under one re-entrant lock and SQLite runs in WAL mode, so there is only
  ever one writer and readers never block it. Network calls to time-proof services happen
  outside that lock, after the record is committed.
- **D-013 · First start.** The UI asks for an author label (self-declared, shown as such)
  and then creates the key pair and the genesis record (`POST /api/identity`). Renaming a
  project uses `POST /api/projects/{id}/rename`; projects are local display data, not
  records.
- **D-014 · Bitcoin anchor is off until OpenTimestamps lands (P1).** Following PRD §17,
  `RPROV_BTC` defaults to `off` while P0 is built; the UI then shows
  "Bitcoin anchor: not enabled". When it is switched on, missing anchors are backfilled for
  old records; their Bitcoin time is later than the record time, which is expected.
- **D-015 · Retry policy for time proofs.** Failed submissions are retried with exponential
  backoff (1 min doubling to a 6 h cap); after 30 attempts the row is marked `failed` but the
  manual refresh still retries it. Pending Bitcoin anchors are re-checked hourly.
