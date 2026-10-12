# Research provenance (v0.3)

**English** · [中文](README.zh.md)

A research record that runs on your own computer. It keeps the ideas, notes, experiments, code, data, figures and publications of a piece of research as **linked records**, gives each record a **signature** and **time proofs**, and so makes "how did this research become what it is now" visible and checkable — by you, and by anyone you share it with.

![Evolution map](docs/screenshots/graph.png)

The full requirements are in [docs/PRD.md](docs/PRD.md) (Chinese). Where the implementation departs from the PRD, or decides something the PRD leaves open, it is written down in [docs/DECISIONS.md](docs/DECISIONS.md).

## What it can show, and what it can't

**It can show:**

- That a record existed no later than a certain time. "The record" means all of it: the files, the type, its relations to other records, and what you wrote.
- That it has not been changed since.
- The order of the records.
- That all records were signed with the same signing key.

**It cannot show:**

- That you thought of it yourself. A signing key only means "the same key", not a particular person.
- That you were the first to think of it.
- Why you made a change.
- That the content is right, or valuable.

In the app and in reports, every piece of information says where it comes from, and the three sources are always shown apart:

| Source | Meaning |
| --- | --- |
| **Verified record** | Signed and time-stamped; anyone can check it. It only shows that the record existed then and has not changed since — not that what it says is true. |
| **Author statement** | What you said: the "why", relations, an earlier date you gave for older material, the local clock time. The app can only show that you said so on that day. |
| AI inference | Only when you optionally retell the Story with a model on your own computer. Shown apart, never saved as a record, never put into a bundle (see "Summarise with an AI model on this computer" below). |

The two time proofs are also always shown apart, never merged into a vague "verified time":

| | **Date stamp** (in reports: third-party timestamp) | **Public stamp** (in reports: Bitcoin anchor) |
| --- | --- | --- |
| Protocol | RFC 3161; [FreeTSA](https://freetsa.org/) by default, [DigiCert](https://www.digicert.com/) when FreeTSA can't be reached | [OpenTimestamps](https://opentimestamps.org/) |
| How long it takes | A few seconds: "Date stamp ✓" | First "Public stamp: waiting", usually "Public stamp: done" a few hours later |
| Whom you rely on | The stamping service's private key and clock; anyone can check its signature | No organisation, only the public Bitcoin blockchain |

**Append-only, never edited.** A record with its proofs can't be changed by anyone, you included. Adding a relation later, marking a key step, adding a note, correcting or retracting are all new records with their own signature and time proofs, and the app shows "added later on such-and-such a day".

## Download and install (no developer tools needed)

For people who don't write code: download an installer and double-click. The app is called **Research History**; it brings its own Python and interface and needs nothing else.

| System | Installer |
| --- | --- |
| macOS 11 or later, Apple silicon (M1/M2/M3/M4) | `ResearchHistory-<version>-macos-arm64.dmg` |
| Windows 10 (1809 or later) / Windows 11, 64-bit | `ResearchHistory-<version>-windows-x64-setup.exe` |

The installers are on this repository's **Releases** page: on the repository's front page, look in the right-hand column under **Releases** and click the newest version (marked **Latest**), or go straight to [github.com/celeste1-ops/research-provenance-platform/releases/latest](https://github.com/celeste1-ops/research-provenance-platform/releases/latest); the files are under **Assets** at the bottom of that page. Every push also builds a copy under **Actions → Package → Artifacts** (you need to be signed in to GitHub; kept for 90 days). There is no installer for Intel Macs yet (Apple menu → About This Mac shows the chip); use "Run from source" below.

**On a Mac, step by step:**

1. Click `ResearchHistory-<version>-macos-arm64.dmg`. The browser saves it in your **Downloads** folder (click the download arrow at the top right of the browser, or open Finder → Downloads).
2. Double-click the `.dmg` file. A window opens with **Research History** and an **Applications** folder side by side, and an arrow and a short note between them saying what to do.
3. Drag **Research History** onto **Applications**. When upgrading, choose **Replace**. You can then close the window, eject "Research History" in the Finder sidebar and delete the `.dmg`.
4. Open **Applications** (Finder → Applications, or Launchpad) and double-click **Research History**. The first time, macOS will warn you: allow it as described in the next section.
5. Your browser opens the app's page, and a blue round icon appears in the menu bar at the top right. That browser page *is* the app: there is no other window.

**On Windows, step by step:**

1. Click `ResearchHistory-<version>-windows-x64-setup.exe`; it goes to your **Downloads** folder.
2. Double-click it (if Windows warns you, see the next section), then click through the installer (Next → Install → Finish).
3. "Launch Research History" is ticked at the end, so your browser opens the app's page; next time, open it from the Start menu. Its icon sits in the notification area at the bottom right (sometimes hidden under the **^**).

The **中文 / English** button at the top right of the page switches the whole app between Chinese and English.

**Using it:** after you open it, the app starts in the background and opens http://127.0.0.1:8765 in your browser (if 8765 is taken, the next free port). A blue round icon appears in the Mac menu bar or the Windows notification area: click it to open the page again, or **Quit**. Closing the browser window does not quit the app; to get the page back, open the app again (double-click it in Applications, Launchpad or the Start menu) or click the icon → **Open Research History**. The app never runs twice at once (the installed app and `make run` won't share one data folder either). The log is `logs/app.log` in the data folder.

**Where your data is:** `~/.rprov` on a Mac, `%USERPROFILE%\.rprov` on Windows (the same place as when running from source, so you can switch between the two). To **upgrade**, install the new version over the old one; **uninstalling** (Mac: drag the app to the Trash; Windows: Settings → Apps → Research History → Uninstall) never deletes your data.

### Opening it the first time: the system will warn you (the installers are not signed yet)

The installers are not signed by Apple or Microsoft yet, so the first time you open one the system says it can't verify the developer. Make sure you downloaded the installer from this repository, then allow it as below; you won't be asked again.

**macOS 14 or earlier:** drag Research History into Applications, then in the Finder **Control-click it (or right-click) → Open**, and click **Open** in the dialog.

**macOS 15 (Sequoia) or later:** the right-click trick no longer works. Double-click the app once (it says it can't be opened; click Done), then open **System Settings → Privacy & Security**, scroll down to Security, click **Open Anyway** next to "Research History was blocked", click **Open Anyway** again in the dialog and enter your login password.

**The keychain asks once after installing or upgrading.** Since 0.3.2 the app keeps everything it needs in the keychain (signing keys, backup password) in a single keychain item, so the first time a new version runs (or after switching between the installed app and `make run`), macOS asks once whether Research History may use it. Click **Always Allow** and enter your login password. (The first time 0.3.2 runs it still asks once for each item older versions made — usually two or three — while it moves them into the single item.) Because the app is not signed by a developer yet, this comes back **after every upgrade**; that is normal, and nothing is lost — the key and the password are still in the keychain. If you click **Deny** (or just **Allow**), the app stops asking: the top of the page says "The Keychain refused access", saving steps and automatic backups wait, and you click **Try again** there when you're ready.

**Windows:** if a blue "Windows protected your PC" (SmartScreen) appears when you open the installer, click **More info → Run anyway**. If Edge says the file "isn't commonly downloaded", click "…" → **Keep** → **Keep anyway**. Installing needs no administrator rights; the app goes into `%LOCALAPPDATA%\Programs\Research History` and appears in the Start menu (a desktop icon is optional). On a freshly installed Windows 11 with **Smart App Control** turned on, unsigned apps may be blocked outright with no "Run anyway" button; the only ways round it are turning Smart App Control off in Windows Security (it may not be possible to turn it back on) or waiting for a signed version. The signing key is kept in the **Windows Credential Manager**.

### Using it in mainland China and other places

Both time proofs need public services abroad: the date stamp uses FreeTSA (DigiCert automatically when FreeTSA can't be reached), the public stamp uses four OpenTimestamps servers, and Bitcoin blocks are checked with blockstream.info and mempool.space. In some places some of these may be blocked or slow.

- **Settings → Check stamp services…** → **Check now** tries each of these services and tells you in one sentence whether a date stamp can be had (and from which service), whether a public stamp can start, and whether Bitcoin blocks can be checked. The check sends only a random test value, never anything of yours.
- **Nothing is lost when a service can't be reached.** Steps are saved on your computer straight away, and missing proofs are fetched later automatically (retried every hour; or click **Settings → Check stamps now**). When a service has just failed, saving doesn't wait for it again for the next 10 minutes, so saving a step doesn't stall each time.
- Clicking Check now again on another network (a phone hotspot, say) shows whether the current network is the problem.

## Run from source (developers, Mac)

You need [uv](https://docs.astral.sh/uv/) (it fetches Python 3.12 or 3.13), Node.js 22 or later, `make`, and OpenSSL 3 (for checking signatures by hand: `brew install openssl@3`; if a newer openssl is also installed, put version 3 first on your PATH).

It also runs from source on Windows (without `make`: `uv sync --extra ots --extra desktop`, `cd web; npm ci; npm run build`, `uv run python -m app.desktop`); the data is in `%USERPROFILE%\.rprov`.

```bash
git clone <this repository> research-provenance-platform
cd research-provenance-platform
make install          # Python dependencies (uv.lock) and interface dependencies (package-lock.json)
make freetsa-certs    # first time: check and update the bundled FreeTSA certificates against freetsa.org, and check the bundled DigiCert root (DECISIONS D-004, D-045)
make run              # opens http://127.0.0.1:8765
```

Opening it the first time takes two steps:

1. Enter your name or a pen name (shown as "self-declared" in reports) and a project name, then click **Start**. The app creates a signing key and stores it in the system's key store (macOS Keychain; Windows Credential Manager), never as a plain file.
2. **Turn on automatic backup**: choose a backup folder and a backup password. From then on, each new step and each new time proof makes the app write a fresh backup there on its own (the latest 10 are kept).

![First run: automatic backup](docs/screenshots/first-run-backup.png)

**Where should backups go?** Somewhere that is not only on this computer: an external drive, or a sync folder you already use (Mac: iCloud Drive, Dropbox, Google Drive, OneDrive; Windows: OneDrive, iCloud Drive from iCloud for Windows, Dropbox, "My Drive" from Google Drive, another drive or a USB stick). The app lists the places of this kind it finds. If the folder you pick is on the same disk as the data, the top bar warns "Backup is on this Mac only" — such a backup can't help if the computer is lost or broken. Backups use your own storage; this tool charges nothing and never handles them.

**Backups are fully encrypted** (`.rprovbackup` files: the database, all attachments and the signing key, encrypted together with AES-256-GCM; opening one needs the backup password or the recovery code). In iCloud or Dropbox, the provider can't see a single title or word of content. **Keep your backup password somewhere safe** — without the password and the recovery code nobody can open the backup, us included. This Mac keeps the password in the keychain so that backups run on their own; you only type it again to restore.

**The recovery code opens a backup when the password is forgotten.** When you turn on automatic backup, the app shows a **recovery code** once (24 letters and digits in 4 groups), and you can click Print. If you forget the backup password, the recovery code opens the backup just as well. The app does not keep the recovery code (only a public key derived from it), so print it or write it down, keep it away from the computer, and not in the backup folder. If you lose it, make a new one under **Backup** (the old one still opens earlier backups). The printed page also shows your **signing key fingerprint** (16 characters): after restoring with the recovery code, the app shows the fingerprint of the key it restored, and the two must match — if they don't, the backup isn't yours; don't use it.

**When you pick a folder, the app says right away where it is**: iCloud Drive / Dropbox (✓ survives losing the computer), another disk (✓), or "This Mac's own disk" (⚠ lost together with the computer). The backup folder can't be inside the app's own data folder. **Don't put the data in use (`~/.rprov`) into iCloud or Dropbox** — syncing can corrupt a database that is in use; only the encrypted backup files belong there. If you put the data folder into a sync folder, the top of the page keeps warning you.

**What if the computer breaks or is lost?** Install the tool on the new Mac, choose **Restore from a backup** the first time you open it, pick the latest `.rprovbackup` file and enter the backup password (if you've forgotten it, click "Forgot the password? Use the recovery code instead" and enter the recovery code). Steps, attachments, time proofs and the signing key all come back as they were; verification gives the same results, and new records belong to the same identity. After a restore, **automatic backup is paused** and the top bar says "Backup paused — confirm to resume": once you're sure this is the Mac you'll use from now on, click **Resume automatic backup to this folder** (choose another folder if the old Mac still backs up to the same one). Moving the whole computer with Migration Assistant or Time Machine works the same way: the app notices the data was copied over and pauses automatic backup until you confirm. **Record on one Mac only**: if the old and new Macs both run the app and back up to the same folder, both show "Another Mac is backing up here too" and a red bar — quit the app on the one you no longer use, or the two will record separately, the history will fork, and a later restore can only bring back one side. After restoring with the recovery code, the app doesn't know the old password and asks you to set a new one. The backup button in the top bar always shows the status (time of the last backup, or why it failed); click it to back up right away, change the folder or password, or download a single backup file.

**Rehearse a restore (recommended; safe on the same Mac too)** with a temporary folder, and keep the copy away from the keychain entirely:

```bash
RPROV_HOME=~/.rprov-restore-test RPROV_KEYSTORE=memory make run PORT=8767
```

Open http://127.0.0.1:8767, choose **Restore from a backup**, pick the latest `.rprovbackup` in the backup folder, restore with the recovery code, and check that the records are all there. In the copy, **don't click Resume and don't add steps**; close it when done and delete `~/.rprov-restore-test` (careful not to delete `~/.rprov`).

Note: the time-proof services (FreeTSA, Bitcoin) only ever receive each step's "fingerprint" (a hash), from which the content can't be read or rebuilt — so they can't give your content back either, Bitcoin included. Only a backup can bring the content back. **Settings → Where is my data?** (also at the bottom of the page) says the same.

To back up the signing key on its own: **Settings → Back up signing key only…** (a full backup already includes the key).

**Practise first, then record for real.** A saved record can't be deleted, so the top of the page has a switch: **My research** (the real record) / **Practice** (a practice space). Practice is a completely separate set of data with its own signing key (in `~/.rprov/practice/`); the top bar turns orange and keeps saying "Practice: nothing here goes into your real record"; steps there are saved straight away, and the button reads **Save practice step**. Practice is never backed up; empty it with **Settings → Start practice over…**, or **Fill practice with sample research** to look around the fictional FSF sample. On the very first start you can also click "Open the practice space".

**Saving to the real record asks once more.** In My research, **Save step** opens "Save this step to your real record?", listing the type, title, start of the text, attachments, which step it relates to and the reason you wrote, with the reminder that once saved it can't be changed or deleted, only added to or retracted. **Save to my record** saves it; **Go back** returns to editing. Adding a relation later, marking a key step, adding a note or retracting also ask first. Switching from Practice back to the real record shows a reminder once.

**A separate sample from the command line?** `make demo && make run` loads the fictional FSF sample (14 records, 9 types, 3 relations, key steps, relations added later, notes, L1/L2 imports, a retraction) into an empty data folder. Records can't be deleted, so move the sample aside before recording real material: `mv ~/.rprov ~/.rprov-demo` (see it again later with `RPROV_HOME=~/.rprov-demo make run`). Or start with `RPROV_HOME=~/.rprov-demo make demo`.

All data is in `~/.rprov/` (permissions 0700). Texts, attachments, titles and notes never leave your computer; the only thing sent out is the hash a time proof needs (the record ID), and the time-proof services see the IP address and time of the request. There is no account, no cloud service of ours, no analytics and no crash reports. Automatic backup only writes an encrypted file into a local folder you chose; if your own iCloud / Dropbox syncs that folder, what leaves the computer is still only that unreadable encrypted file (DECISIONS D-033).

## Chinese / English

The top right of the app (on the welcome page the first time) has a **中文 / English** button: one click switches the whole interface to the other language. The first time, the app follows the browser's language. The choice is remembered, and the menu bar / tray menu follows it.

- **Only the app's own words are translated.** Your titles, texts, notes and reasons are shown exactly as you wrote them, never translated.
- **Reports can be in either language.** Exporting has a "Report language" setting, the interface's language by default; `report.html` and `VERIFY.md` both have a Chinese version. The output and failure codes of `verify.py` are always English (it is the same checker for every reader).
- **The Windows installer** speaks Chinese on Chinese Windows and English elsewhere.

This README uses the English button names.

## How to use it

1. **Create a project**, for example "FSF".
2. **+ Add a step** (in an empty project you can also click a card such as "Idea" or "Experiment"): choose a type (idea, note, claim/hypothesis, document, code, experiment, data, figure, publication), write a title and text (Markdown), and attach files: drag them from the Finder / Explorer anywhere onto the form, or click "choose files". Dropping files onto the main page opens a new step with them attached.
   - For code you can just give the repository address and commit, but that is only an external reference: if the repository is deleted later, that code is gone. To keep the code itself, also attach a `git archive` file.
   - For a published paper, give its DOI or address (a third-party reference, L2).
3. **+ Connect to an earlier step**: say how it relates to an earlier step — a new version (revises), developed from it (derived from), or uses it (uses). You can add a sentence on "why", shown as an author statement; important steps can be marked "Mark as a key step".
4. Click **Save step**. Within seconds it shows "Date stamp ✓", a few hours later "Public stamp: done". Every term has a small "?" next to it that opens a one-sentence explanation.
5. **Adding older material**: tick "This is older material I'm adding now". It can only show that the material existed on the day it was recorded; an earlier date you give is shown as an author statement (L1), and one backed by an outside record such as a DOI, an email or a web archive is marked L2.
6. **Look at your steps.** **Steps** shows one card per step, oldest at the top: what kind of step it is, its date and stamps, and in plain words which earlier steps it came from ("Grew out of #1 …", "Builds on #2 …"); click a #number to go to that step, or "Table" for every record with both stamps. **Map** shows the same steps as boxes, older on the left, in rows by kind, with lines between related steps; the row names stay at the left edge, a short legend explains the lines, and pointing at a step shows only its lines. **Key steps only** shows just the key steps. Click any step to see its content, both time proofs, the author's statements and what was added later; the record ID, hashes and signature are under "Technical details". The number in the top bar counts research steps only — not the first "genesis" record, nor relations and notes added later.

![Record detail](docs/screenshots/detail.png)

### Less typing: quick notes, watched folders, recording from git

- **Quick note**: the button in the top bar, or "Quick note…" in the menu bar / tray menu. There is one box: the first line is the title, the rest the text; Save (or ⌘/Ctrl+Enter) stores it as a note, with time stamps like any other step.
- **Watch a folder (Settings → Watch a folder…)**: choose the folder of a piece of work (drafts, data, figures) and a project. When a file there is new or changed and then stays unchanged for two minutes, it counts as a new version:
  1. Its fingerprint gets a date stamp right away (only the hash is sent), and a copy goes into the **inbox** — it is **not** in your record yet.
  2. The top bar shows "Inbox (n)". For a version worth keeping, click "Record as a step": the title, type and "new version" relation are already filled in. Click "Throw away" for the rest; nothing is left behind.
  3. The recorded step keeps the date stamp from when it arrived (`<file name>.tsr` next to the file), so it loses no time: the report, `verify.py` and the `openssl` commands in `VERIFY.md` can all check that the file existed when it arrived in the inbox.
  - Hidden files, Office and editor lock and temporary files, folders such as `.git`, and files over 50 MB are skipped; a folder with more than 2000 files is refused (most likely the wrong folder).
  - Copies in the inbox stay in the app's data folder on this computer and are not backed up; once recorded as a step, they are recorded and backed up like any other step.
- **Record from git (Settings → Record from git…)**: choose a git repository folder on your computer and a branch, and from then on **every new commit** on that branch becomes a "code" step on the map: the title and text come from the commit message, the external reference is the commit, and it "revises" the step of the previous commit. While the app runs it looks once a minute; on the next start it catches up on the commits in between (more than 20 at once become one step that lists them).
  - Only the local repository is read: nothing is fetched or pushed, and GitHub is never contacted; what leaves the computer is still only the fingerprints the time stamps need. Git must be installed.
  - Earlier history can be recorded too: in parts at each tag, or by month without tags (by year if it goes back far), one step per part. **The dates git shows are only author statements** (they can be changed), so these steps are marked as older material added now, and their dates are shown as claimed dates (L1), not verified times; likewise, any commit date earlier than today counts only as an author statement.
  - Optionally "Keep a copy of the code with each step (zip)": the code can then be checked even if the repository is deleted or rewritten, but each commit stores a copy of the whole repository (up to 50 MB each). Without it, only the commit is recorded, and the app says "External reference, code content not saved".
  - A tagged commit is marked as a key step automatically; a tag added later marks that step as a key step through an "added later" record. A mark you removed is never added again.
  - In My research, every recorded commit is a permanent step. You can "Stop recording" at any time; steps already recorded stay.

### Story: the research told in sentences, without AI

The **Story** tab tells each step, and what was added later, in order and in fixed sentences, for example: "On 2026-05-03 the author recorded an experiment: “Numerical experiment 1”. The author noted that it builds on “Formula v1”."

- **No AI, nothing added.** Every sentence comes from the records themselves; "why" appears only where you wrote a reason, quoted as you wrote it.
- **Every sentence names its source:** the record number and date (✓ marks a date-stamp time); click to open that step. Your own statements (reasons, notes, claimed dates, and the relations between steps) are highlighted.
- **Parts:** each part ends at a key step; without key steps, by month.
- **Take it with you:** save it as Markdown or print it to PDF. The shared report (`report.html`) has this section too, written only from what the bundle discloses: a record shared as "existence only" appears only as "record n is not disclosed".
- In Chinese and English, following the interface language; the report follows the report language chosen when exporting.

### Summarise with an AI model on this computer (optional)

At the top of the Story tab is "AI summary…" (and at its bottom "Summarise with an AI model on this computer (optional)…"). The model writes a short summary in sections — In one sentence, How it started, What happened, Turning points, Where it stands now — each point ending with the steps it comes from, which you can click. The text appears as it is written, with the time taken so far; **Stop** ends it at any time (the model really stops). A local model usually needs one to three minutes; the first time it also has to load. You first need a model running on your own computer, for example [Ollama](https://ollama.com) (for Chinese, a model such as Qwen; 16 GB of memory is best) or LM Studio.

- **Only this computer.** Only `127.0.0.1`, `localhost` or `::1` are accepted as addresses (Ollama uses `http://127.0.0.1:11434` by default, LM Studio `http://127.0.0.1:1234`); any other address is refused. Proxies are not used and redirects not followed, so nothing leaves the computer: the promise that content stays on your computer holds.
- **It is given only the Story's sentences** (titles, the reasons and notes you wrote), never the text or attachments of steps.
- **Every sentence must name the steps it comes from** (for example [#12]). The app checks each sentence: one that names no step, names a step that doesn't exist, or claims what records can't show (originality, authorship, who owns an idea, who had it first) is crossed out, and left out when saving as Markdown.
- Its text is always labelled **"AI inference"**, in its own colour, apart from verified records and author statements; it is **never saved as a step** and never put into a bundle. It runs only when you click "Write the summary".

## Sharing: export an evidence bundle

Click **Share** and choose, record by record, how much to disclose:

| Disclosure | The reader sees |
| --- | --- |
| Everything | All content |
| Structure only | Type, title, relations, author statements, times; not the text (but the hashes of the text and attachments) |
| Existence only | "Record n existed no later than such-and-such a time" |

Before exporting you get a preview of what each record discloses. Two things to keep in mind: "Structure only" discloses the hashes of the text and attachments, so content someone already has or can easily guess could be confirmed against them; and the bundle's `chain.json` shows how many records there are up to the last exported one.

The evidence bundle is a zip:

```text
report.html     web report; opens offline and prints to PDF from the browser
verify.py       standalone checker
VERIFY.md       steps for checking by hand (sha256sum / openssl / ots commands)
manifests/ payloads/ content/ signatures/ proofs/ certs/ identity/ chain.json bundle.json
```

![Report](docs/screenshots/report.png)

## How to verify (for readers)

The reader doesn't need this tool, and doesn't need to trust you or us:

```bash
pip install "cryptography>=44" "rfc3161-client>=1.0.6"
python3 verify.py provenance-FSF-2026-10-12.zip      # or run it on the unzipped folder
```

To check Bitcoin anchors, `verify.py` asks two public block explorers (blockstream.info, mempool.space) for block headers, sending only the block height. With your own Bitcoin node use `--bitcoin-node http://user:pass@127.0.0.1:8332`; to stay fully offline use `--offline` (Bitcoin anchors then show as "not checked" — neither a failure nor a time).

It checks each record: the content hashes (V1), manifest and payload (V2), signature (V3), third-party timestamp (V4, against the bundled FreeTSA and DigiCert roots, whose fingerprints it prints at the end), Bitcoin anchor (V5), log chain (V6) and references (V7). Each record's result is *Pass*, *Pass (Bitcoin anchor pending)*, *Warning* or *Fail* (with a failure code). Exit code 0 means no record failed.

Readers who'd rather not run a program can check the same things by hand with `sha256sum`, `openssl` and `ots`, following `VERIFY.md`.

## Development

```bash
make dev              # backend (auto-reload) + Vite dev server at http://127.0.0.1:5173
make test             # ruff + all tests (unit, API, tamper, end-to-end); network tests skipped
make test-network     # tests against real FreeTSA / DigiCert / OpenTimestamps / block explorers (incl. AC-09), on a Mac with internet
make verify-py        # rebuild dist/verify.py from the core library
make tsa-fixture      # save real FreeTSA / DigiCert responses as offline test samples (on a Mac with internet; commit them under tests/fixtures/tsa/)
```

Offline development can use mock time proofs: `RPROV_TSA=mock RPROV_BTC=mock make run` (proofs from a mock authority, which `verify.py` doesn't trust by default; for tests only add `--tsa-root certs/mock-tsa-root.pem`). A Linux development environment without a keychain also needs `RPROV_KEYSTORE=dev-insecure-file` (a plain key file, for development only).

**Building the installers** (DECISIONS D-044):

```bash
bash packaging/build_macos.sh          # on a Mac: dist/Research History.app and the .dmg, with a smoke test
# Windows (needs Inno Setup 6):
#   ./packaging/build_windows.ps1; ./packaging/smoke_windows.ps1
```

The GitHub Actions **Package** workflow builds both installers on every push and tries each one end to end (install, start, set up, save a step, export, check with the exported verify.py, data still there after uninstalling). To release a new version: set `version` in `pyproject.toml` and commit, then push the matching tag (for example `git tag v0.3.0 && git push origin v0.3.0`), or, once merged to main, open **Actions → Package → Run workflow** on GitHub, choose main, tick **release** and run it. The workflow creates a **draft** Release with both installers and `SHA256SUMS.txt`; check it and click Publish on GitHub (with the second way, the tag is created when you publish). The release notes come from `packaging/RELEASE_NOTES.md`. Running again while a draft exists leaves it as it is; to redo a draft, delete it on GitHub first and run again. Downloads from GitHub can be slow in mainland China; the same files can also be put on a local cloud drive or object storage, together with `SHA256SUMS.txt` so people can compare.

**What signing would take later:**

- **macOS**: join the Apple Developer Program (99 USD a year) and get a "Developer ID Application" certificate; sign the build with it (hardened runtime on), submit it for notarization with `xcrun notarytool submit --wait`, and staple the result into the .dmg with `xcrun stapler staple`. Users can then just double-click, and the keychain no longer asks after upgrades. The certificate and an App Store Connect API key can be stored as GitHub Secrets so the Package workflow signs and notarizes automatically.
- **Windows**: a code-signing certificate is needed. Options: Microsoft's cloud signing service (Azure Trusted Signing, now Artifact Signing, about 10 USD a month, currently open to organisations and individuals in some countries and regions only — see Microsoft's site), or an OV code-signing certificate from a certificate authority (about 200–500 USD a year; the private key must be on a hardware token or in a cloud HSM). Sign the installer and app with `signtool` and add a timestamp (such as `http://timestamp.digicert.com`). After signing, the "Run anyway" prompt fades as downloads accumulate (SmartScreen reputation builds up; even EV certificates no longer skip it immediately), and Smart App Control lets the app through.
- **Intel Macs**: build another copy on an Intel macOS runner (`macos-13`), or build one package for both chips with a universal2 Python and dependencies; the code itself doesn't change.

Code layout: `core/provenance_core/` is the only library with trust logic (JCS, hashing, signing, the log chain, replay, verification, the time-proof interfaces); `app/` is the local service (FastAPI + SQLite); `web/` is the interface (React + TypeScript); `tools/build_verify.py` builds the single-file `verify.py` from the core library.

## Progress

- **P0 done**: append-only records, signing, replay; third-party timestamps (RFC 3161); evidence bundle export, `report.html` (with a static evolution map), `verify.py`, tamper tests; the record form and evolution map.
- **P1 done**: Bitcoin anchors (OpenTimestamps) and block-explorer checks; the key-steps-only view; the timeline view; the full detail panel (Verified record / Author statement / Later additions / Changes, with adding relations, key steps, notes and retractions from the panel); backup and restore; the FSF sample data.
- **Round 4 (installers)**: macOS (Apple silicon) and Windows 10/11 installers, a menu bar / notification area icon, a single running copy; Windows backup-location suggestions, and the full test suite (browser tests included) on GitHub Actions; DigiCert as a fallback for date stamps; Settings → Check stamp services checks whether each time-proof service can be reached (DECISIONS D-043 – D-045).
- **v0.3.4**: step cards and map boxes show what each step says — the first lines of its text, its files, its code commit or DOI — without opening it (DECISIONS D-056).
- **v0.3.3**: the page no longer stays empty on Windows computers whose registry calls `.js` files plain text; a page that cannot start says what to do (DECISIONS D-055).
- **v0.3.2**: one keychain item, so a new version asks once; opening the app again while it runs shows its page; files can be dragged onto the page and the form; a clearer two-row layout (D-053); Steps as plain-language cards first, a map with row names and a legend, and an AI summary in short sections that appears as it is written and can be stopped (D-054); the disk image window says to drag the app onto Applications (DECISIONS D-052).
- **v0.3.1**: after an upgrade the keychain is asked once, not every few seconds; a refusal is not retried until you click Try again (DECISIONS D-051).
- **Round 5 (v0.3.0)**: the Chinese / English switch — the interface, the app's own texts and error messages, exported reports and VERIFY.md, the menu bar / tray menu and the Windows installer (DECISIONS D-046); quick notes and recording commits from a local git repository (D-047); the Story without AI (D-048); watched folders and the inbox (D-049); optional retelling by a local AI model (D-050).
- **To be done on a Mac with internet**: `make freetsa-certs`, `make test-network` (AC-09: a real FreeTSA `.tsr` verified with `openssl ts -verify`; a real DigiCert timestamp; real OpenTimestamps calendars and block explorers), and the 4 manual checks in section 16 of the PRD.
