## 下载 · Downloads

| 系统 | 文件 |
| --- | --- |
| macOS 11 或更新，Apple 芯片（M1/M2/M3/M4） | `ResearchHistory-<版本>-macos-arm64.dmg` |
| Windows 10（1809 或更新）/ Windows 11，64 位 | `ResearchHistory-<版本>-windows-x64-setup.exe` |

`SHA256SUMS.txt` 里是每个文件的 SHA-256，下载后可以对照（macOS：`shasum -a 256 文件名`；Windows PowerShell：`Get-FileHash 文件名`）。

这两个安装包**还没有签名**，第一次打开时系统会拦一下，放行方法见 README 的「下载安装」一节。数据放在 `~/.rprov`（Windows：`%USERPROFILE%\.rprov`），升级和卸载都不会动它。

These installers are not signed yet; see "下载安装" in the README for how to open them the first time.
