## What's in this version (v0.3.2)

**Fixed in v0.3.2**
- **One keychain question per upgrade.** Everything the app keeps in the keychain is now in a single item, so a new version asks once — click **Always Allow**. (This first time, 0.3.2 asks once for each item older versions made, usually two or three, while it moves them into the single item.)
- **Opening the app again shows its page.** If you closed the browser window, double-click Research History in Applications or Launchpad and the page opens again.
- **Drag files in.** Drag files from the Finder or Explorer anywhere onto the "Add a step" form; dropped onto the main page, they open a new step with them attached.
- **A clearer layout.** The top is now two rows: where you are (space, project, backup, settings) and what you can do (Map / List / Story as buttons with icons; Quick note, Share, Add a step). A short line at the bottom says how to use the view in front of you, and Settings is grouped.
- **The disk image says what to do.** The window that opens with the `.dmg` shows an arrow and a short note: drag Research History onto Applications, then open it from there.

**Fixed in v0.3.1**
- After an upgrade, the keychain question no longer comes back every few seconds; after Deny the app stops asking and offers **Try again** at the top of the page.

**Also in this version**, from v0.3.0 (the first public installers):

**New in v0.3.0**
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

## How to install

**Mac:** click the `.dmg` file below; it goes to your Downloads folder. Double-click it: a window opens with **Research History**, an arrow and **Applications**. Drag Research History onto Applications (choose Replace when upgrading; quit the running app first with the menu bar icon → Quit). Then open Applications and double-click Research History. Your browser opens the app's page, and a blue round icon appears in the menu bar.

**Windows:** click the `.exe` file below; it goes to your Downloads folder. Double-click it and click through the installer (Next → Install → Finish). Your browser opens the app's page; next time, open it from the Start menu.

The **中文 / English** button at the top right of the page switches the app between Chinese and English.

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
- On a Mac, the first time a new version runs, macOS asks whether it may use what the app keeps in the keychain: click **Always Allow** and enter your login password. Because the app is unsigned, this comes back after each upgrade; nothing is lost.
- **Windows:** if "Windows protected your PC" (SmartScreen) appears, click **More info → Run anyway**. On a new Windows 11 with Smart App Control turned on, unsigned apps may be blocked with no way to run them until a signed version is available.

A Chinese guide is in [README.zh.md](https://github.com/celeste1-ops/research-provenance-platform/blob/main/README.zh.md) (中文说明见 README.zh.md).
