## What's in this version (v0.3.0)

The first public installers of Research History. They contain everything built so far.

**New in this version**
- **Chinese / English.** One switch changes the whole app: the interface and its messages, the exported report and VERIFY.md, the menu bar / tray menu, and the Windows installer.
- **Quick note.** A button in the top bar and an item in the tray menu: type a line and it is saved as a note, with its date stamp like any other step.
- **Record from git.** Pick a repository and branch on your computer, and every new commit becomes a "code" step. Only the local repository is read; nothing is fetched or pushed.
- **Story.** The research told in fixed sentences, without AI. Each sentence names the records it comes from, and the story can go into the exported report.
- **Watched folders and inbox.** When a file in a watched folder has a new version, it gets a date stamp and waits in the inbox; you decide whether it becomes a step.
- **Retell with an AI model on this computer (optional).** Works only with a model running on your own computer, such as Ollama or LM Studio. Its text is labelled "AI inference", every sentence must name its records, and it is never saved as a record.

**Already there**
- Append-only, signed records with two separate time proofs: a date stamp (RFC 3161, from FreeTSA, with DigiCert as a fallback) and a public stamp (OpenTimestamps).
- The map, a key-steps-only view, a timeline, and a detail panel that keeps verified records, author statements and later additions apart.
- Evidence bundles with `report.html` and a single-file `verify.py`, so anyone can check them without installing this app.
- Automatic encrypted backup with a recovery code, a practice space, and Settings → Check stamp services.

## Downloads

| System | File |
| --- | --- |
| macOS 11 or later, Apple silicon (M1/M2/M3/M4) | `ResearchHistory-<version>-macos-arm64.dmg` |
| Windows 10 (1809 or later) / Windows 11, 64-bit | `ResearchHistory-<version>-windows-x64-setup.exe` |

`SHA256SUMS.txt` lists the SHA-256 of each file, to compare after downloading (macOS: `shasum -a 256 <file>`; Windows PowerShell: `Get-FileHash <file>`).

Your data is kept in `~/.rprov` (Windows: `%USERPROFILE%\.rprov`). Upgrading or uninstalling never touches it.

## Opening it the first time (the installers are not signed yet)

macOS and Windows warn about apps from unidentified developers. Make sure you downloaded the file from this page, then:

- **macOS 14 or earlier:** drag Research History into Applications, Control-click it (or right-click) → **Open**, then **Open** again.
- **macOS 15 or later:** double-click it once and close the warning, then go to **System Settings → Privacy & Security**, scroll to Security and click **Open Anyway** next to Research History; confirm with **Open Anyway** and your password.
- On a Mac, the first time the app stores its signing key it asks to use the keychain: click **Always Allow**. Because the app is unsigned, it asks again after each upgrade; the key is still there.
- **Windows:** if "Windows protected your PC" (SmartScreen) appears, click **More info → Run anyway**. On a new Windows 11 with Smart App Control turned on, unsigned apps may be blocked with no way to run them until a signed version is available.

A Chinese guide is in [README.zh.md](https://github.com/celeste1-ops/research-provenance-platform/blob/main/README.zh.md) (中文说明见 README.zh.md).
