## 这一版有什么 · What's in this version (v0.3.0)

第一个公开的安装包，包含到目前为止的全部功能。

**新加的（第 5 轮）**
- **中文 / English 一键切换**：界面、提示和错误信息、导出的报告和 VERIFY.md、菜单栏 / 托盘菜单、Windows 安装程序都有中英文。
- **快速记一笔**：顶栏按钮或托盘菜单里的「快速记一笔…」，写一行就存成一条笔记，照样拿时间章。
- **从本机 git 自动记录**：选一个仓库和分支，以后每次提交自动变成一个「代码」步骤；只读本机仓库，不连 GitHub。
- **研究经过**：不用 AI，用固定句式把记录讲成一段经过，每句都标出出自哪几条记录，可以放进导出的报告。
- **盯住文件夹 + 收件箱**：文件夹里的文件有了新版本，先盖日期章放进收件箱，你决定要不要记成一步。
- **用本机 AI 重新讲述（可选）**：只连你自己电脑上的模型（如 Ollama、LM Studio），写出来的内容标成「AI 推断」，不会存成记录。

**之前就有的**
- 只追加的记录、签名、两种时间证明（日期章 RFC 3161：FreeTSA，连不上时用 DigiCert；公开章：OpenTimestamps）。
- 演化图、只看里程碑、时间线、详情侧栏（可验证记录 / 作者陈述 / 后来补加的 / 改了什么）。
- 导出证据包：`report.html` + 单文件 `verify.py`，别人不用装这个程序也能自己检查。
- 自动加密备份（含恢复码）、练习空间、Settings → Check stamp services 检查时间证明服务能不能连上。

**New in this version (round 5):** Chinese / English switch for the whole app, report and installer; quick note from the tray; recording commits from a local git repository; the Story (the research told in sentences, without AI, each sentence pointing at its records); watched folders with a date-stamped inbox; optional retelling by a language model on your own computer, labelled AI inference and never saved as a record. Everything from earlier versions is included: append-only signed records, date stamps (RFC 3161) and public stamps (OpenTimestamps), map / timeline views, evidence bundles with `report.html` and a standalone `verify.py`, encrypted automatic backup and the practice space.

## 下载 · Downloads

| 系统 | 文件 |
| --- | --- |
| macOS 11 或更新，Apple 芯片（M1/M2/M3/M4） | `ResearchHistory-<版本>-macos-arm64.dmg` |
| Windows 10（1809 或更新）/ Windows 11，64 位 | `ResearchHistory-<版本>-windows-x64-setup.exe` |

`SHA256SUMS.txt` 里是每个文件的 SHA-256，下载后可以对照（macOS：`shasum -a 256 文件名`；Windows PowerShell：`Get-FileHash 文件名`）。

这两个安装包**还没有签名**，第一次打开时系统会拦一下，放行方法见 README 的「下载安装」一节。数据放在 `~/.rprov`（Windows：`%USERPROFILE%\.rprov`），升级和卸载都不会动它。

These installers are not signed yet; see "下载安装" in the README for how to open them the first time.
