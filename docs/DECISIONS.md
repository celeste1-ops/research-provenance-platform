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

  *Update (2026-10-11, done on the Mac):* `make freetsa-certs` confirmed the root fingerprint
  and replaced `tsa.crt` with FreeTSA's current TSA certificate (serial `C2E986160DA8E9CD`,
  valid 2026-02-15 → 2040-02-02, SHA-256
  `32e841a95cc1164101ffde41298ef2fc75c1c4372ef095e88a6bbd47dfb191fc`), which is directly
  issued by the pinned root. `make test-network` (AC-09 and the OpenTimestamps /
  block-explorer checks) passed on the Mac with OpenSSL 3.

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
- **D-014 · Bitcoin anchor was off until OpenTimestamps landed (P1).** Following PRD §17,
  `RPROV_BTC` defaulted to `off` while P0 was built; the UI then showed
  "Bitcoin anchor: not enabled". It now defaults to `ots`. Missing anchors are backfilled
  for older records; their Bitcoin time is later than the record time, which is expected.
- **D-015 · Retry policy for time proofs.** Failed submissions are retried with exponential
  backoff (1 min doubling to a 6 h cap); after 30 attempts the row is marked `failed` but the
  manual refresh still retries it. Pending Bitcoin anchors are re-checked hourly.

## Evidence bundle and verify.py

- **D-016 · verify.py trusts only what it carries.** The FreeTSA root is embedded in the
  generated `verify.py` (with its fingerprint asserted); `certs/` in the bundle is for the
  manual `openssl` commands only and is never used as a trust anchor by `verify.py`. A
  reader who deliberately trusts another TSA root passes `--tsa-root PEM`.
- **D-017 · Exit codes.** `verify.py` exits 0 when no record failed (warnings and pending
  Bitcoin anchors allowed), 1 when any record failed, 2 when the bundle cannot be read.
- **D-018 · How verify.py is built.** `tools/build_verify.py` concatenates the core modules
  it needs (der, jcs, ots, proofs, records, signing, chain, verify, bundle, verify_cli),
  strips the package-relative imports, refuses any import outside the standard library,
  `cryptography` and `rfc3161-client`, and fails on duplicate top-level names. The Bitcoin
  `.ots` reader is a standard-library implementation cross-checked against the official
  `opentimestamps` library in the tests, so `opentimestamps` stays optional.
- **D-019 · Selection semantics.** An export takes a disclosure level per record plus a
  default for the rest. The bundle covers seq 0 up to the highest record that is disclosed
  (or explicitly chosen); every other record in that range is "existence only". Non-entry
  records cannot be "full" (they have no content) and are downgraded to "structure".
- **D-020 · Markdown in report.html.** Rendered with markdown-it-py with raw HTML and images
  disabled (images would trigger network requests); the report also carries a
  `default-src 'none'` Content-Security-Policy, so it cannot load anything.
- **D-021 · End-to-end tests use Playwright for Python.** They run inside pytest (`make
  test`). Where the bundled Playwright browser build is missing (this cloud image), the
  pre-installed Chromium is used via `executable_path`; CI installs the matching browser.

## User interface

- **D-022 · Graph layout without dagre.** PRD §11 fixes the layout: records left to right by
  `seq`, one row per node type that occurs. That is a deterministic grid, so the graph
  computes positions directly instead of running dagre (which the PRD lists as optional
  and replaceable). React Flow (`@xyflow/react`, MIT) draws it.
- **D-023 · P0 user interface scope.** The P0 UI has first-start setup, the record form
  (CodeMirror 6 Markdown editor, file drop, code/publication references, relations, "why",
  milestone, import options), the evolution graph, a record sidebar split into Verified
  record / Author statement / Later additions, and the export dialog with preview. The
  milestones-only view, the timeline view, sidebar actions for later additions, the
  "Changes" diff section and backup/restore screens follow in P1.
- **D-024 · The session token is injected by the backend.** The built `index.html` keeps a
  `__RPROV_SESSION_TOKEN__` placeholder that the local server replaces per launch; the Vite
  plugin that fills it during `make dev` only runs on the dev server.
- **D-025 · How Bitcoin anchors are checked.** The app and `verify.py` check a Bitcoin
  attestation against the block header from a local node (`RPROV_BITCOIN_RPC` /
  `--bitcoin-node`) or, by default, from two public block explorers (blockstream.info,
  mempool.space) that must agree; results say "checked via block explorers". Only block
  heights are sent. `verify.py --offline` makes no requests and reports the attestation as
  "not checked" (neither verified time nor failure). The app shows "Bitcoin anchor:
  confirmed" only after that header check succeeds; until then the anchor stays pending.
- **D-026 · OpenTimestamps details.** As the official client does, a 16-byte random nonce
  is appended to the record ID and hashed before submission, so calendars only see
  SHA-256(record ID ‖ nonce). The proof is submitted to the four default calendars and
  needs at least two answers. Upgrades only contact calendars on the official whitelist.
  Proofs are built with the official `opentimestamps` library (an install extra); the
  verifier reads them with its own standard-library reader.

## Sample data

- **D-027 · `make demo` only loads into an empty data directory.** Records cannot be
  removed, so loading the fictional FSF sample into a directory that already holds records
  would mix it into a real chain forever; the loader refuses instead. On a clean machine
  `make demo && make run` works as the PRD's manual check expects (both use `~/.rprov`).
  Before recording real material, move the demo aside (`mv ~/.rprov ~/.rprov-demo`) or load
  the demo with `RPROV_HOME=~/.rprov-demo make demo` from the start. The demo uses whatever
  time-proof providers are configured. All sample text is fictional.

## Backup and restore

- **D-028 · Backup format and restore rules.** A backup is one zip (`rprov.backup/1`): a
  consistent SQLite snapshot (taken under the write lock with SQLite's backup API), every
  stored file, the signing key encrypted with the backup password, and an index with the
  SHA-256 of every member. The database and files are not encrypted (they are the
  author's own data, kept in a place the author chooses); the key always is (PRD S5).
  Restore only goes into an installation without records and only inserts rows, so it
  never edits anything; afterwards the whole chain is re-verified and the key returns to
  the keychain. S4: only the expected member names are accepted, absolute paths, `..`,
  backslashes and symbolic links are refused, the total uncompressed size is capped
  (20 GiB) and every member is read with a size cap and checked against the index.
- **D-029 · Backup location.** The backup folder is an absolute path typed in the backup
  dialog (a browser cannot hand a folder path to the local server); it is remembered and
  the button stays highlighted until one is set. After the first record the app reminds
  the author to set it (PRD S7).

## Round 2: data durability and first-run experience

Feedback after the first real run: the interface spoke to engineers, and "what if the Mac
breaks?" had no good answer (a manual backup the author has to remember is not one). These
decisions change presentation and backup only — not the record format, the chain, the
verification rules or what leaves the machine for time proofs.

- **D-030 · Automatic encrypted backup (PRD S7, refines D-028/D-029).** The author picks a
  backup folder and a backup password once (first-run step 2, or later from the top bar).
  After every change the app writes a new backup there, debounced by 20 seconds; the hourly
  time-proof job also writes one when a proof was upgraded since the last backup. The
  newest 10 backups of this installation are kept; older ones are removed. Files are
  written to a `.partial` name, flushed and then renamed, so a crash never leaves a broken
  backup under the real name. A failure (drive unplugged, folder gone) is shown in the top
  bar and retried on the next change or hour; it never stops recording.
- **D-031 · Backups are now fully encrypted (supersedes the "not encrypted" part of
  D-028).** A backup file (`.rprovbackup`) is a short magic line, a JSON header (format,
  KDF parameters, salt, nonce) and the D-028 zip encrypted with AES-256-GCM under a key
  from scrypt (N = 2^17, r = 8, p = 1) of the backup password; the header is authenticated
  as associated data, and an implausible N is refused before any work is done. Reason: the
  folder is now usually a synced one (D-033) and therefore sits on someone else's servers;
  titles and content must not be readable there. A wrong password and a damaged file give
  the same error (GCM cannot tell them apart). The inner zip, its member checks (S4) and
  the separately encrypted signing key are unchanged, and restore still accepts the older
  unencrypted zips made before this change.
- **D-032 · The backup password is kept in the system keychain.** Unattended backups need
  it, and asking for it on every change would defeat "automatic". It is stored next to the
  signing key (same keychain service family, item `backup-password:<installation>`), never
  in the database or a file. It is needed again only to restore. After a restore the same
  password is stored again, so backups to the same folder simply continue on the new Mac.
- **D-033 · Synced folders and PRD rule 3 ("no cloud sync").** The app still uploads
  nothing: writing a file into a local folder is a local operation, and the only network
  traffic remains the time-proof requests (the providers-only network test is unchanged).
  If the author chooses a folder that their own iCloud Drive, Dropbox, Google Drive or
  OneDrive client syncs, that client — a service the author already uses and pays for, if
  at all — moves an encrypted file the provider cannot read. This is the closest fit to the
  PRD's intent (no accounts, no service of ours, content never readable outside the Mac)
  while answering S7's "data loss is the most realistic risk". The app offers such folders
  and external drives (`/Volumes/*` on another device) as suggestions, labels where a
  folder really is, and warns when the folder is on the same disk as the records, because
  such a backup does not survive a lost or broken Mac.
- **D-034 · Plain names in the interface.** "Record" becomes "research step" in the
  interface ("Add research step", "Save step", "+ Connect to an earlier step", "Mark as a
  milestone", "This is older material I'm adding now"); "Export" becomes "Share…". The
  fixed source labels (Verified record / Author statement / Later additions) and the two
  separate time-proof lines are unchanged (rule 2 and 4), with one plain sentence under each
  proof saying what it means. Record IDs, hashes and signatures move into a collapsed
  "Technical details" block; the key-only backup, "Check timestamps now" and installation
  details move into a "⋯" menu.
- **D-035 · Step counts leave out the genesis record and later additions.** The top bar
  counts research steps (entries) in the current project. A fresh install therefore shows
  "0 research steps" instead of "1 records", which read as a bug. The total record count,
  including genesis, links, notes, milestones and retractions, is still shown under
  Technical details; the chain itself is unchanged.
- **D-036 · First run and empty project.** First run is two steps: name and project, then
  automatic backup (skippable; skipping keeps a reminder in the top bar, in the empty state
  and after each save). A third path restores from a backup. An empty project shows what
  the tool does and one card per kind of step; choosing a card opens the form with that kind
  selected. The graph legend is shown on request ("How to read the graph"), and "Where is my
  data?" explains in plain words where data lives, what the timestamp services receive
  (only a fingerprint, so they cannot give anything back) and how to restore on a new Mac.

## Round 3: plain words, practice space, recovery code

- **D-037 · Plain names for the two stamps in the app (PRD §9 table, rule 4).** The PRD
  lists the interface text "Third-party timestamp: verified" and "Bitcoin anchor: pending /
  confirmed". At the author's request the app now says **"Date stamp ✓"** and **"Public
  stamp: waiting / done"** (also "not yet", "off"), with D and P as the small icons. Rule 4's
  intent is kept: the two proofs keep separate names, separate lines, separate status and
  separate columns, and nothing merges them into one "verified time". Every place a stamp
  is shown has a "?" whose one sentence names the formal term, and the Share dialog and the
  record's Technical details say which formal name each stamp has. Reports, `VERIFY.md`,
  `verify.py` and the API's `text` field keep the formal names unchanged, because they are
  read by third parties and the evidence bundle must not change. Other plain words: "Add a
  step", "Map", "List", "Key steps only" (milestone), "Share", "Settings" (was "⋯").
- **D-038 · Practice space and confirmation before saving to the real record.** Records
  can never be removed (rule 1), so a new user trying the app would leave test steps in
  their real record forever. The app therefore has a second, completely separate space,
  **Practice**, one click away in the top bar (and on the first screen). It is its own
  installation in `<data folder>/practice`: own database, own files, own signing key (a new
  installation ID, so a separate keychain item), own genesis record labelled "<name>
  (practice)". Practice steps get the same stamps as real ones (only hashes leave, as
  always), so practice looks exactly like the real thing; it is never backed up. Practice
  can be started over or filled with the fictional FSF sample; that deletes the practice
  folder and its key — the only delete anywhere in the app, never offered for the real
  record. Each request names its space in a header (or `?space=` on plain links) and goes
  to the real record otherwise, so a tab always saves where it says it saves. Practice is
  marked everywhere (orange top bar, striped banner "Practice: nothing here goes into your
  real record", "Save practice step"). In the real record, saving a step — and every later
  action (key step, link, note, retraction, withdrawing a link) — first shows exactly what
  will be saved and that it can't be changed or deleted afterwards ("Save to my record" /
  "Go back"). Switching from practice to the real record shows that reminder once. This
  adds no accounts and changes nothing about records, signatures, stamps, verification or
  the evidence bundle.
- **D-039 · Printable recovery code (backup format 2) and backup-location checks.** A
  forgotten backup password used to mean unreadable backups. When automatic backup is
  turned on, the app now also shows a **recovery code** once (24 characters, 120 random
  bits, Crockford base32 in four groups) with a Print button, and asks the author to tick
  that they kept it. The code is never stored: the app keeps only the public half of an
  X25519 key derived from it (scrypt, N = 2^14, since the code itself is random). Backup
  format 2 (`RPROV-BACKUP-ENC/2`) encrypts the inner zip with a random backup key and
  stores that key twice in the authenticated header: wrapped with the password-derived
  key (scrypt, as in D-031) and wrapped to the recovery public key (ephemeral X25519 +
  HKDF-SHA256 + AES-GCM). Either one opens the backup. The signing key inside the zip is
  encrypted with a key derived from the backup key, so a recovery-code restore brings it
  back too. After such a restore the old password is unknown, so automatic backup asks
  for a new one; the same recovery code keeps working. A new code can be made at any time
  (older backups keep opening with the old one). Format 1 and the original unencrypted
  zips still restore. Location checks: while the author picks a folder the dialog says
  where it really is ("This Mac's own disk — if this Mac is lost or breaks, this backup
  is lost with it", a synced service, or another disk); a folder inside the app's data
  folder is refused; and if the live data folder itself sits inside iCloud Drive, Dropbox
  or another synced folder the app warns on every page, because syncing can damage a
  database in use — only the encrypted backup files belong in such a folder.
- **D-040 · A restored copy never backs up by itself; each copy prunes only its own files.**
  Found in a restore drill on the author's Mac: a restore copies the backup settings
  (folder, "automatic on"), and on the same Mac the keychain already holds the backup
  password for that installation ID, so the drill copy would have written into the real
  iCloud folder within the hour and pruned the real copy's files together with its own
  (both used the same file-name prefix). A password restore would also have replaced the
  keychain's current backup password with the older one from the backup. Now: (1) every
  restore pauses automatic backup (`backup_auto = 0`, marked "restored"); the top bar says
  "Backup paused — confirm to resume" and the Backup dialog offers "Resume automatic
  backup to this folder" or a different folder, with the advice not to resume a test
  copy or a second Mac sharing the folder. (2) Backup file names carry a short per-copy
  id (`rprov-backup-<installation>-<copy>-<time>`), reset by every restore, and rotation
  only removes files with this copy's id. Files named before this change are never
  removed automatically. (3) A restore never replaces keychain entries that already
  exist for the installation: the backup password is kept as it is, and the signing key
  is only written when missing; if the keychain holds a *different* key for that
  installation the restore stops before changing anything. The recommended drill still
  uses a separate data folder and `RPROV_KEYSTORE=memory`, so the copy does not touch the
  keychain at all (README).
- **D-041 · Two copies backing up into one folder are told about each other.** After a
  move to a new Mac the old one may keep running. Since D-040 the two copies no longer
  delete each other's files, but both could keep adding steps under the same identity,
  and the history would split: a later restore brings back only one branch. Each copy
  now looks at the backup folder: a file from another copy of the same installation
  (a different per-copy id), written after this copy's starting point, means a second
  copy is active. For a restored copy the starting point is the restore, so the files
  it came from don't count; files named before per-copy ids existed count only for a
  restored copy (for the original they are its own past). Then the top bar says
  "Another Mac is backing up here too", a red banner says to use only one Mac to add
  steps, and the Backup dialog explains why, with "The other copy is gone — stop
  warning" (it comes back if that copy writes again) or "Choose a different folder".
  The paused box after a restore shows the same warning before "Resume". Backups
  continue meanwhile: each copy's own files are complete and kept apart. The app does
  not try to decide which Mac is "the real one" or merge the two histories; it makes the
  situation visible so the author can stop one of them.
- **D-042 · Hardening after an independent review of the backup code.**
  1. *Copied data folders.* Migration Assistant, a Time Machine restore or `cp -r` copy
     the database (and on a Mac usually the keychain), so the copy carried the
     original's per-copy id and the two would have pruned each other's backups without
     any warning. The copy id is now tied to the data folder on disk (inode and creation
     time). At start-up a folder whose identity no longer matches is treated like a
     restore: a new copy id, automatic backup paused until the author confirms ("this
     data folder was copied from somewhere else"), and the original's files count as
     another copy's from then on.
  2. *Per-copy keychain entries.* The backup password is now stored per copy
     (`backup-password:<installation>:<copy>`). A restore drill on the same Mac can no
     longer change the original's password, even by choosing another folder and
     password in the copy. The original install takes over the older entry name once;
     restored or copied installs never read it.
  3. *Pause enforced by the server.* While paused, `run`, the manual "Back up now" and
     "new recovery code" refuse; only "Resume" or setting the folder and password again
     ends the pause. After a recovery-code restore (no password known), the paused box
     asks for a new password instead of skipping straight to the setup form.
  4. *Format 3, in pieces.* AES-GCM in `cryptography` takes at most 2 GiB per message,
     so a large research folder would have made every backup fail. Format 3
     (`RPROV-BACKUP-ENC/3`) encrypts the inner zip in 4 MiB pieces under the same random
     backup key and key slots. Each piece's nonce is a random prefix plus its number,
     and its associated data is the header, its number and a last-piece flag, so pieces
     can't be reordered, dropped or cut off. Backups are now built, encrypted, uploaded
     for restore and decrypted through temporary files in the data folder, so memory
     use no longer grows with the research. Formats 2 and 1 and plain zips still restore.
  5. *Bounded key derivation.* A crafted header can no longer ask for more than 256 MiB
     of scrypt memory (n a power of two, r ≤ 32, p ≤ 4) in any format.
  6. *Saving never waits for a backup.* Scheduling the next backup and running one use
     separate locks.
  7. *Recovery-code restores show the signing key.* The recovery key is public (it sits
     in every header), so anyone able to write into the backup folder could leave a
     file that opens with the code. Password restores are not affected. The recovery
     sheet now prints the first 16 hex digits of the signing public key. After a
     recovery-code restore the app shows the key it brought back and asks the author to
     compare the two before opening the app. Sheets printed before this change have no
     such line; making a new recovery code prints one.
  8. Recovery codes may be typed with any kind of dash.

## Round 4: installers, Windows, reachability of the stamp services

- **D-043 · Windows 10/11 as a second system (PRD §4 conflict).** PRD §4 lists "web and
  mobile versions" as out of scope and says to get the Mac version right first; it does
  not mention Windows. The author asked for Windows 11 support so the app can be shared
  with others. It is the same local app (no account, no cloud, 127.0.0.1 only), so none
  of the §4 reasons apply; it is added as a second desktop system, not as a web version.
  1. *Wording.* The interface says "this Mac", "this PC" or "this computer" and names the
     system's credential store (Keychain, Windows Credential Manager) from
     `Settings.device` (`RPROV_DEVICE` overrides). Tests pin "Mac".
  2. *S5 (PRD §14).* "The private key is stored only in the macOS Keychain" is read as
     "only in the system's credential store": on Windows `keyring` uses Windows
     Credential Manager (DPAPI, tied to the Windows account). Never a plain file, as
     before; exported backups still need a password.
  3. *Backup folders.* Suggestions per system: OneDrive (personal and work), iCloud for
     Windows, Dropbox (also a custom location from its `info.json`), Google Drive's "My
     Drive" on any drive letter, other drives. Only fixed, removable and network drives
     are looked at, and the scan is cached for a minute (probing a drive that is not
     ready can take many seconds). The "live data in a synced folder" warning works the
     same on every system.
  4. *Portability fixes.* UTF-8 for all text files and for verify.py's output (a piped
     Windows console used to crash on non-ASCII titles); LF line endings kept by
     `.gitattributes` for hash-checked fixtures; "Start practice over" reports a folder
     that Windows still keeps in use instead of reopening the old practice data.
  5. *CI.* A `windows-latest` job runs the whole suite, browser tests included.

- **D-044 · Desktop app and installers.** For people who will not install Python, uv and
  Node: a double-clickable app named "Research History".
  1. *Same server, no new network code.* `app/desktop.py` starts the usual local server
     (127.0.0.1; the next free port if 8765 is taken), opens the default browser and
     shows a menu bar / notification area icon with "Open Research History" and "Quit".
     Readiness is read from the server object, so the rule "network code only in
     providers" still holds. One copy per data folder: an OS file lock in the data folder
     (released even after a crash); a second start just opens the browser at the running
     copy. With no console window, everything goes to `<data>/logs/app.log`, including
     tracebacks of unexpected server errors. `make run` / `python -m app` take the same
     lock and refuse to start while the installed app (or another `make run`) is using the
     data folder.
  2. *Bundles.* PyInstaller, one folder, with its own Python, the built interface, the
     report templates, the sample data and the public TSA certificates. The two public
     mock-TSA certificates are included because export compares token issuers with the
     mock root; the spec refuses to package any file whose name contains "key". The
     frozen app has no core sources to assemble verify.py from, so a verify.py built at
     packaging time from the same core is shipped and used for exports.
  3. *Windows.* Inno Setup, per user (no administrator rights), installed into
     `%LOCALAPPDATA%\Programs\Research History`, Start menu entry, optional desktop icon,
     uninstaller. Data stays in `%USERPROFILE%\.rprov`; uninstalling and upgrading never
     touch it. The `AppId` must never change, or upgrades become a second installation.
  4. *macOS.* `.app` in a `.dmg`, Apple Silicon first (Intel needs a build on an Intel
     runner or a universal2 Python and wheels; the code itself is ready). Menu bar only
     (`LSUIElement`), macOS 11 or later. Data stays in `~/.rprov`.
  5. *Not signed yet.* macOS gets an ad-hoc signature only, Windows none. First-open
     steps and what signing would take are in the README. Because an unsigned app has no
     stable identity, macOS asks again for Keychain access after every upgrade
     ("Always Allow").
  6. *Built and tested on GitHub Actions.* `package.yml` builds both installers on every
     push to main and to `claude/**` branches, on `v*` tags and on demand, installs each
     one silently, sets up a throwaway data folder (never `~/.rprov`, never the real
     Keychain on macOS), saves a step with a non-ASCII title, exports, runs the bundled
     verify.py on the export, uninstalls and checks the data folder is still there.

- **D-045 · A second time-stamping authority, and checking whether the stamp services
  can be reached.** Some of the public services may be blocked or slow in some places,
  mainland China in particular. Facts the design rests on: saving a step waits for its
  date stamp; a step without one is still saved and gets it later from the retry job.
  1. *DigiCert as fallback, FreeTSA first.* `http://timestamp.digicert.com` (DigiCert's
     public RFC 3161 service: free, no account, widely used for code signing) is tried
     when FreeTSA does not answer. FreeTSA stays
     first so nothing changes where it works and existing bundles keep the same layout.
     `RPROV_TSA=digicert` reverses the order; `RPROV_TSA_FALLBACK=off` disables the
     fallback. One timestamp per record, from whichever authority answered; the stored
     row and the token itself name the signer.
  2. *Built-in root, pinned.* DigiCert Trusted Root G4 (valid 2013-08-01 → 2038-01-15,
     SHA-256 `55:2F:7B:DC:F1:A7:AF:9E:6C:E6:72:01:7F:4F:12:AB:F7:72:40:C7:8E:76:1A:C2:03:D1:D9:D2:0A:C8:99:88`),
     committed next to the FreeTSA root and checked against its fingerprint whenever it
     is loaded. The copy came from the operating system trust store (DigiCert's download
     server is not reachable from the cloud environment); `make freetsa-certs` now also
     compares it with `https://cacerts.digicert.com/DigiCertTrustedRootG4.crt`. Each
     authority accepts only tokens chaining to its own root; checking (app, verify.py,
     report) accepts either root. Unknown roots are still refused (TSA_CHAIN_UNTRUSTED).
  3. *Plain HTTP is fine here.* DigiCert documents its timestamp endpoint as plain HTTP.
     The request holds just the 32-byte digest and a nonce, and the answer is checked in
     full (signature, chain to the pinned root, digest, nonce) before it is accepted, so
     an eavesdropper learns nothing new and a tamperer can only make the stamp fail.
  4. *No slow saves while a service is blocked.* An authority that failed is moved to
     the back of the line for an hour, so the next saves go straight to the one that
     works. If a whole kind of stamp could not be reached (no authority, or fewer than
     two OpenTimestamps calendars), saves skip it for 10 minutes instead of waiting for
     its time limit again; the record stays "waiting" and the retry job and "Check stamps
     now" still try. So only one save in ten minutes waits for an unreachable service.
  5. *Bundles and verify.py.* `certs/` always holds both roots;
     `certs/digicert-tsa-chain.pem` holds the DigiCert signing chain when a record was
     stamped by DigiCert (`freetsa-tsa.crt` as before for FreeTSA). `bundle.json` lists
     both fingerprints under `trusted_tsa_roots`; VERIFY.md gives an `openssl ts -verify`
     command for each authority; verify.py embeds both roots and prints both
     fingerprints. Bundles exported before this change verify exactly as before.
  6. *Certificates in DER order.* DigiCert's tokens list their certificates (responder,
     intermediate, root) in chain order. DER requires a SET in sorted order, and
     rfc3161-client refuses such a token (`InvalidSetOrdering`), so the fallback failed on
     every real response (found on the Mac). The certificates are not covered by the
     signature, so the app sorts them before reading or storing a token, and the check
     (app and verify.py) sorts them too. Lengths and everything signed stay the same, and
     `openssl ts -verify` accepts the result. `make tsa-fixture` saves real responses
     into `tests/fixtures/tsa/`; an offline test checks every saved one.
  7. *"Check stamp services" (Settings menu).* Runs only when the author clicks "Check
     now". It asks each authority for a real stamp of a random value (the answer is
     checked like a real one), asks each of the four calendars about a random value
     they have never seen, and asks both block explorers for the current block height.
     Nothing from the author's work is sent. All checks run at once with the usual
     time limit; the result says in plain words what works (date stamps, public stamps
     starting, finished public stamps being checked) and that nothing is lost while a
     service is unreachable.

- **D-046 · Chinese and English.** The author asked for both languages and a switch. PRD §7
  rule 5 applies to both: no Chinese text may claim more than the English does.
  1. *One button, the whole app.* "中文 / English" in the top bar (and on the welcome page)
     switches the interface, the texts the server writes (record views, backup folder
     advice, service check results, error messages), the menu bar / tray menu and, by
     default, the exported report. The first choice follows the browser's language. The
     choice is stored in the browser and in `<data>/preferences.json`, so the desktop
     menu can read it before any page is open and a second browser follows it.
  2. *English text as the key.* Every text is written in English in the code; Chinese
     comes from `web/src/locales/zh.ts` (interface) and `app/locales/zh.py` (server and
     report). The interface sends its language with each request (`X-RPROV-Lang`). Error
     messages are written in English where they arise and translated where they leave
     the server, by matching them against the catalogue's error patterns; values inside
     them are kept. tests/unit/test_i18n.py fails when a text has no Chinese version, a
     translation loses a placeholder or a tag, or a Chinese text makes a forbidden claim.
  3. *Only the app's own words.* Titles, notes, reasons, file names and project names are
     never translated. Values are inserted after the template's markup is read, so an
     author's text can never become markup, and Chinese spacing (a space between Chinese
     and Latin letters) is only added to the app's own words and where a value meets
     them, never inside the value.
  4. *The report.* `report.html` and `VERIFY.md` are written in the language chosen in
     the export dialog (default: the interface's). The Chinese "what it proves / does
     not prove" text follows PRD §2. Records, hashes, signatures and proofs are the same
     whatever the language; only the words around them change. `VERIFY.zh.md.j2` gives
     exactly the same commands as the English guide (a test compares them). `verify.py`,
     its failure codes and the core library's messages stay English: they are the one
     checking program any reader runs.
  5. *Installer.* The Windows installer shows Simplified Chinese on a Chinese Windows and
     English elsewhere, without asking; the official Inno Setup translation is kept in
     `packaging/windows/` (Inno Setup 6.5 or later). The app's name stays "Research
     History" in both languages.
  6. *Developer messages stay English* (wrong `RPROV_*` settings, a missing keystore
     backend), as do the logs.

- **D-047 · Recording with less effort: quick note and local git commits.** The author asked
  for this in round 5 ("lazy users won't record by hand"). PRD §4 left automatic GitHub
  import for later because git dates can be changed and a full import would not fit v0.1;
  this keeps to that reasoning: only *local* repositories, and git's dates never count as
  verified times.
  1. *Quick note.* A one-box dialog (top bar, and "Quick note…" in the menu bar / tray menu,
     which opens the page at `#quick-note`). The first line is the title, the rest the body;
     it is saved as a `note` entry and stamped like any step. In the real record the box
     itself says the note is permanent; there is no second confirmation, because the point
     is to make a note in one go.
  2. *Recording a git repository.* Settings → "Record from git…": a folder on this computer,
     a branch and a project. From then on each new commit on that branch (first-parent
     line) becomes a `code` entry: title = commit subject, body = the rest of the message
     (the author's own words), `external = {repo_url, commit}`, `revises` the previous
     commit's entry. A background job looks every minute while the app runs and catches
     up after a restart; more than 20 new commits at once become one entry listing them.
     A commit already recorded (same repository address and commit) is never recorded
     twice, even if the app stopped between saving the step and updating its list.
  3. *git dates are the author's statement.* A commit made on an earlier day than the day
     it is recorded, and every history entry, carries `import` = {claimed date, L1}: shown
     as "older material added now" with the claimed date as an author statement. Commits
     recorded the same day carry no date of their own; their date stamp is the time.
  4. *History, once.* Optionally the history before that point is added as a few entries:
     one per tag, untagged stretches per month (per year when that would make more than 48
     entries), each listing its commits and pointing at the newest; they `revises` each
     other in order. They are saved in the background because each waits for its stamps.
  5. *Code copy is a choice.* "Keep a copy of the code with each step" attaches the
     commit's files as a zip (up to 50 MB; above that only the reference is kept). Off by
     default: it stores the whole repository once per commit. Without it the entry is an
     external reference and the interface says the code content was not saved (AC-16).
     The zip holds every file exactly as committed (read with `ls-tree` and `cat-file`), not
     `git archive`, which converts line endings by the computer's settings (found on Windows,
     where LF became CRLF) and runs filter programs such as Git LFS that may use the
     network. Fixed file dates make the same commit give the same zip everywhere.
  6. *Only local, read-only git.* The app runs the author's own `git` with rev-parse,
     symbolic-ref, for-each-ref, log, merge-base, remote get-url, ls-tree and cat-file —
     never fetch, pull or push — with `core.fsmonitor` off, no console window on Windows, and arguments
     checked (full hashes, existing branch names) so nothing can be read as an option.
     `repo_url` is the `origin` address with any password or token removed, or the folder
     path when there is no remote; like every entry field it stays local unless the author
     discloses it in a bundle. Apps started from the Dock or Start menu do not get the
     shell's PATH, so the usual install places are tried; on a Mac without the developer
     tools `/usr/bin/git` is not used (it would only offer to install them).
  7. *Where the list lives.* `<data folder>/git_sources.json`, per space (the practice space
     has its own). It is not part of backups: folder paths differ between computers, and
     every recorded step is in the backup anyway.
  8. *Tags are key steps.* A commit that has a tag when it is recorded, and a history entry
     that ends at a tag, is recorded as a key step. A tag made later marks the commit's entry
     with a milestone record (a later addition, visibly later). Each tag is applied once:
     the list keeps the tags already handled, so a mark the author takes off stays off.

- **D-048 · The research told in sentences, without AI ("Story").** The author asked for an
  automatic account that does not need AI, to read alongside the map and to put in reports.
  1. *Fixed sentences, nothing added.* `app/services/narrative.py` walks the records in
     recording order and writes one paragraph per step and per later addition from fixed
     templates (English and Chinese): what was recorded and when, older material with its
     claimed date, the links the author declared, the author's reason (quoted as written),
     the commit, DOI or files it refers to, key-step marks, notes, corrections and
     retractions. It never uses the body text and never states a cause the author did not
     write.
  2. *Every sentence keeps its source.* Each sentence lists the records it comes from and is
     either "record" (what was recorded) or "author" (reasons, notes, claimed dates and the
     links between steps — author statements, PRD §2). The interface and the report
     highlight author sentences and show, once per paragraph, the record number and its
     date (✓ when it is a date-stamp time; otherwise the computer's clock), linked to the
     step. The three kinds of information stay apart: this text is not a verified record
     and not an AI inference; it is labelled as generated from the records.
  3. *Parts.* A part ends at each step the author marked as a key step; without key steps,
     one part per month.
  4. *Where it appears.* A "Story" tab next to the map and the list (per project, with
     "Save as Markdown" and print), and a section "The research, step by step" in
     `report.html`. The report builds it only from what the bundle discloses: a record
     disclosed as existence only appears as "record #n is not disclosed here", and nothing
     of its content (a test checks this), exactly like the rest of the report.

- **D-049 · Watched folders and a stamped inbox.** The author asked for new versions of files to
  be recorded automatically. Recording every save directly would fill an append-only record
  with versions nobody wants (editors save every minute), so — as proposed and approved —
  new versions wait in an inbox first.
  1. *What counts as a new version.* Once a minute the app looks at each watched folder (the
     same job as the git recording). A file that is new or changed and then stays unchanged
     for two minutes is a version, if its SHA-256 differs from the last version seen. Hidden
     files and folders, editor/office lock and temporary files, `.git`, `node_modules` and
     similar folders, `*.tsr` and files over 50 MB are skipped. A folder with more than 2000
     files, or one that contains (or is inside) the app's data folder, is refused. Files
     already there when watching starts are not new, unless the author asks for up to 100 of
     them to be put into the inbox.
  2. *Stamped on arrival.* The version's bytes are copied to `<data folder>/inbox/files/` and
     its SHA-256 is sent to the time-stamping authority at once (the same providers and
     fallback as for steps; only the hash leaves). If no authority answers, it waits and is
     retried every minute. The inbox is outside the signed record: a version can be thrown
     away and nothing of it remains. The inbox is not backed up.
  3. *Recording keeps the earlier stamp.* "Record as a step" makes an entry (type guessed from
     the extension, title the file name, both editable; "revises" the step of the file's
     previous recorded version) that holds the file and, next to it, the inbox timestamp as
     `<name>.tsr`. No format change: it is an ordinary attachment. By convention an
     attachment `<name>.tsr` next to `<name>` is a timestamp of that file's bytes;
     `provenance_core.verify.file_stamps` checks it like any RFC 3161 token (signature, chain
     to a trusted root, digest = SHA-256 of the file) and reports "file X existed by T". It
     does not change the record's own result, and the record's own stamp is still the
     record's time. The app, verify.py (text and `--json`), the report (a row per file and a
     sentence in the story) and VERIFY.md (an `openssl ts -verify -data <file>` command, only
     in bundles that hold such a stamp) all show it. A file disclosed as "structure only" has
     no content in the bundle, so its stamp cannot be checked there and is not shown.
  4. *Per space.* Each space has its own watched folders (`watched_folders.json`) and inbox.

- **D-050 · An optional retelling by a language model on the author's own computer.** PRD §4
  left AI for a later version and set its rules: answer only from the records, point every
  important sentence at its records, label it "AI inference" and keep it apart, and either ask
  before sending anything to an AI company or use a model on the author's computer. The
  author asked for the local model first (round 5); a cloud service is not part of this.
  1. *Only this computer.* `provenance_core/providers/local_ai.py` (the one place network code
     may live) speaks the chat API that Ollama, LM Studio and llama.cpp's server share
     (`/v1/models`, `/v1/chat/completions`). It accepts only loopback addresses (127.0.0.0/8,
     ::1, localhost; no user info), ignores proxy settings and does not follow redirects, so
     a request cannot go anywhere else. The promise that content stays on the computer is
     unchanged.
  2. *What the model is given.* The template story (D-048) as numbered facts — the sentences
     the author already sees, each with its record number, date (✓ for a date stamp) and
     whether it is a record or an author's statement — plus rules: use only these facts, cite
     them after every sentence ([#12]), give reasons only where the author did and say so,
     and never speak of being first, authorship, originality or ownership. Never the bodies
     of steps or their files.
  3. *Every sentence is checked.* A sentence that names no record, names one that is not in
     the story, contains a forbidden claim (`app/services/claims.py`, now shared with the
     tests) or talks about what records can never show (originality, authorship, ownership,
     being first — stricter than the check on the app's own texts) is crossed out with the
     reason, and left out when the text is saved.
  4. *Labelled and apart.* The text is shown under the story in its own colour as "AI
     inference — written by <model> on <date>; it may be wrong". It runs only when the author
     clicks "Write". It is **not saved as a record** (PRD §4 rule 5 would make it a new record
     kind, which old verifiers do not know — as proposed, a format change waits until it is
     needed) and it is never put into a bundle; it can be saved as a Markdown draft labelled
     AI inference, without the crossed-out sentences. The address and model chosen are
     remembered in `preferences.json`.

- **D-051 · The keychain is asked once, and a refusal waits for "Try again".** With a new
  version installed, opening the real record made the keychain question come back without end:
  the page asks the server for its status every few seconds, and each answer read the backup
  password from the keychain again. macOS asks about every read by an app that is not signed by a
  developer of an item it did not create itself (after every upgrade the app counts as new),
  unless the person chose "Always Allow"; after "Deny" the status even became an internal error.
  1. *Read once.* The backup password is read the first time it is needed and remembered per
     keychain entry while the app runs (setting a new one updates it). The status no longer
     needs the signing key at all: the key fingerprint shown on the recovery sheet comes from
     the identity's first record. So a new version asks at most twice: the backup password,
     then the signing key when the first backup or step needs it.
  2. *A refusal is not retried by itself.* One gate in `KeyringKeyStore`, shared by the real
     record and practice: after the keychain refuses (`KeyringLocked`), nothing touches the
     keychain again — so the system does not ask again — until the person clicks **Try again**
     at the top of the page, which asks for both items right away. Meanwhile the status
     answers normally with `keychain_denied`; the backup pill says it waits; a backup is
     skipped without being recorded as a failure; saving a step answers 403 with a message the
     page shows (not an internal error).
  3. README and release notes say that a new version asks once or twice and that "Always
     Allow" is the answer; signing the app (README, "What signing would take") would end it.

- **D-052 · One keychain item, reopening shows the page, files can be dropped anywhere, and the
  disk image says what to do.** Feedback on 0.3.1 from the first real installation:
  1. *One keychain item.* After the upgrade the login password was asked five times: an app
     without a developer signature is asked about every keychain item it did not create, after
     every upgrade, and the app had one item per key and secret (real signing key, practice
     signing key, backup password, older backup-password entries). On macOS everything now lives in
     one item (`rprov` / `secrets`, JSON with `keys` and `secrets`), read once per run and shared
     by the real record and practice; so a new version asks once. (Windows Credential Manager
     asks nothing and limits an item to 2.5 KB, so there every key and secret keeps its own.) Items of older versions are
     moved into it the first time each is needed (asked once each, that one time) and are left
     in place, because deleting another version's item would make the system ask again. An item
     that cannot be read is never overwritten. Signing the app (README) would remove the
     question entirely.
  2. *Opening the app again shows its page.* On macOS, opening an app that is already running
     only re-activates it; this app has no window, so nothing seemed to happen ("after closing
     it, it won't open"). The app now answers the reopen event by opening its page, as a second
     start already did on Windows.
  3. *Files can be dropped anywhere.* Only the small attachment box took dropped files, and a
     file dropped elsewhere made the browser leave the app to show it. Now the whole form takes
     them, files dropped on the main page open a new step with them attached, and a stray drop
     never replaces the app.
  4. *The disk image says what to do.* The window that opens with the .dmg shows the app and
     Applications side by side on a picture with an arrow and, in English and Chinese, "drag
     onto Applications, then open it from Applications or Launchpad; the first time: Open
     Anyway" (`packaging/macos/`, drawn by `tools/dmg_background.py`, laid out with dmgbuild).
     Windows uses an ordinary installer, which needs no such step.

- **D-053 · Two rows at the top: where am I, and what can I do.** The first row had grown to a
  dozen controls with five "?" buttons, and Map / List / Story looked like plain words, so people
  did not see they could be clicked. Now:
  1. *Row 1, where am I:* the app's mark and name, the My research / Practice switch, the project
     (the list ends with "+ New project…") and its number of steps; on the right the backup and
     inbox status, Settings and the language.
  2. *Row 2, what can I do:* the three views as one segmented control with icons (the chosen one
     raised), one "?" that explains all three and holds the map's legend, "Key steps only" as a
     toggle; on the right the actions — Quick note, Share and the primary Add a step — with
     icons. Their explanations moved into tooltips.
  3. *How to use the view in front of you* is a small line at the bottom of the canvas ("click a
     step to open it · drag to move · scroll to zoom"; for the list and the story what clicking
     does), until the person clicks "Got it".
  4. *Settings is grouped:* Record automatically, Stamps, Your data, Practice, About.
  5. Everything clickable shows it: a pointer, and a change under the mouse (steps on the map,
     rows of the list, the story's step numbers as small chips, buttons, the backup pill).

- **D-054 · Steps as cards first; a map that explains itself; the AI summary in sections, shown as
  it is written.** People found the map hard to read ("can someone with no background follow
  it?"), and the local-AI retelling took minutes with nothing on screen, then came back as long
  prose. Now:
  1. *Steps is the first view.* One card per step, oldest at the top, joined by a line: its kind
     (one colour per kind, the same in every view), title, date (✓ when it comes from a date
     stamp) and stamps, then in plain words where it came from — "Grew out of #1 …", "Builds on
     #2 …", "A new version of #4 …" (later links and withdrawals say so) — and which later steps
     build on it. A #number goes to that step and opens it. "Key steps only" works here too,
     with "n more steps in between". The table of every record (PRD §11's timeline: both stamps
     in their own columns, local time marked unverified) is one click away ("Cards / Table").
     The tabs are Steps / Map / Story; the last one chosen is remembered in the browser.
  2. *The map explains itself.* The names of the rows stay at the left edge however far the map
     is moved, with faint bands to follow a row; a short legend in plain words sits in a corner
     until hidden ("each box is one step: older on the left, newer on the right; each row is one
     kind; a line joins two related steps"); each box shows its #number and its kind's colour;
     pointing at a step fades everything it has no line to and names its lines. The map opens
     where the newest steps are, with every row in sight. In Chinese it is called 关系图.
  3. *The AI summary comes in sections of short points* — In one sentence / How it started /
     What happened / Turning points / Where it stands now — each point ending with its steps,
     in everyday words with technical terms explained. The checks of D-050 are unchanged (every
     sentence is checked; flagged ones are crossed out and left out when saving). An answer is
     limited to 1,500 tokens, which bounds the wait.
  4. *It shows up as it is written, and can be stopped.* The server asks the model for a
     streamed answer and passes it on line by line; the page shows the text growing, how long it
     has taken, and "starting the model…" while a model is loaded the first time. Stop (or
     leaving the story) makes the server close its connection to the model at once (cancelling the
     wait, or only shutting the socket, could leave it open on Windows), so the model stops writing — also while it is
     still loading. Opening the panel looks for models at the saved
     address at once, and a button at the top of the story goes to it, so one click on Write is
     enough.

- **D-055 · The page's own files have fixed types.** v0.3.2 showed an empty page on a friend's
  Windows computer. The server let Python's mimetypes module name the type of each file it
  sends, and on Windows that module reads the registry, where other software often maps `.js`
  to `text/plain`; the page's script then arrived as plain text (with `nosniff`), the browser
  refused to run it, and only the background showed. The server now names the types of the
  page's own files itself (`WEB_TYPES` in `app/main.py`), and the page holds a short note, in
  Chinese and English, that appears after a few seconds if the app has not replaced it ("quit
  the app from its tray / menu bar icon and open it again; if it stays, send a screenshot").
  Tested by making the type table answer `text/plain`, in the API tests and in a browser.
