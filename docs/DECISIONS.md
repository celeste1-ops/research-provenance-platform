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
