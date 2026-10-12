## What's in this version (v0.4.0)

**New in v0.4.0**
- **Its own window.** Research History now opens in a window of its own, like any other program, instead of a browser tab. It uses the web engine your system already has (Safari's on a Mac, Edge's on Windows), so the download is only about 1–2 MB larger.
- **Closing the window does not stop the app.** Date stamps, backups, watched folders and git recording keep running in the menu bar (Mac) or the notification area by the clock (Windows); the first time, the icon says so. Open the window again from that icon, by opening Research History again, or (Mac) from the Dock. To stop everything, choose **Quit** in the icon's menu (Mac: also ⌘Q).
- **Everything works as in the browser.** Drag files in; print the recovery code (or save it as a PDF); save an evidence bundle or an attachment, now with a dialog that asks where; DOI and GitHub links open in your browser. A picture opens larger inside the window, and a new project is named in a proper dialog. Copy and paste work as usual.
- **The browser is still there.** "Open in browser" in the icon's menu opens the same page in your browser. On a Windows computer without Edge's web engine (Microsoft Edge WebView2 Runtime), the app uses the browser as before.

**New in v0.3.4**
- **See what each step says without opening it.** Every step card now shows the first lines of the step's text, its attached files (click one to download it) and its code commit or DOI; a step with only a title says so. The boxes on the map show one line of it too. Click a card to see all of it.
- **Pictures and text files in place.** Attached pictures show on the step's card and in its detail; text files (notes, CSV, code) show what they say; other kinds (Word, PDF, archives) open with the program they belong to. DOIs and repository addresses open on the web.
- **Point at a step on the map** to see what it says.
- **Earlier dates are shown as such.** Material added later shows the day it was added (that is what the date stamp proves); an earlier date the author gave appears next to it as "not verified".
- **The shared report shows content on hover.** In `report.html`, pointing at a step shows what it says, as far as it was shared; a step or file that was not shared says so in plain words. Shared pictures are shown, shared files linked, links open on the web. Still no scripts in the report.

**Fixed in v0.3.3**
- **The page no longer stays empty on some Windows computers.** Where other software had told Windows that `.js` files are plain text, the app sent its own script as plain text, the browser would not run it, and the page at `127.0.0.1:8765` stayed blank. The app now always names the type of its own files. If the page ever cannot start, it says what to do instead of staying empty.

**Fixed in v0.3.2**
- **One keychain question per upgrade.** Everything the app keeps in the keychain is now in a single item, so a new version asks once — click **Always Allow**. (This first time, 0.3.2 asks once for each item older versions made, usually two or three, while it moves them into the single item.)
- **Opening the app again shows its page.** If you closed the browser window, double-click Research History in Applications or Launchpad and the page opens again.
- **Drag files in.** Drag files from the Finder or Explorer anywhere onto the "Add a step" form; dropped onto the main page, they open a new step with them attached.
- **A clearer layout.** The top is now two rows: where you are (space, project, backup, settings) and what you can do (Steps / Map / Story as buttons with icons; Quick note, Share, Add a step). A short line at the bottom says how to use the view in front of you, and Settings is grouped.
- **Steps in plain words.** The first view is one card per step, oldest at the top: what kind of step it is, its date and stamps, and which earlier steps it came from ("Grew out of #1", "Builds on #2"). Click a #number to go to that step; "Table" shows every record.
- **A map that explains itself.** The row names stay in sight, a short legend explains the lines, and pointing at a step shows only its lines. It opens at the newest steps.
- **AI summary in short sections.** The optional summary by a model on your own computer now comes as a few headed lists of points (in one sentence, how it started, what happened, turning points, where it stands now), each point linked to its steps. The text appears as it is written, with the time taken so far, and **Stop** really stops the model.
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

**Mac:** click the `.dmg` file below; it goes to your Downloads folder. Double-click it: a window opens with **Research History**, an arrow and **Applications**. Drag Research History onto Applications (choose Replace when upgrading; quit the running app first with the menu bar icon → Quit). Then open Applications and double-click Research History. Its window opens, and a blue round icon appears in the menu bar.

**Windows:** click the `.exe` file below; it goes to your Downloads folder. Double-click it and click through the installer (Next → Install → Finish). The app's window opens; next time, open it from the Start menu.

The **中文 / English** button at the top right of the window switches the app between Chinese and English.

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
