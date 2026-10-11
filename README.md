# 研究演化证据工具 · Research provenance (v0.1)

装在你自己电脑上的研究记录工具。它把研究过程中的想法、笔记、实验、代码、数据、图和发表记成**互相连接的记录**，给每条记录留下**签名**和**时间证明**，让「这个研究是怎么一步步变成现在这样的」看得见、查得到，别人也能自己检查。

![演化图](docs/screenshots/graph.png)

完整需求见 [docs/PRD.md](docs/PRD.md)；实现中与 PRD 有出入或 PRD 没定的地方，记在 [docs/DECISIONS.md](docs/DECISIONS.md)。

## 它能证明什么，不能证明什么

**能证明：**

- 这条记录最晚在某个时间已经存在。「这条记录」指全部内容：文件、类型、和其他记录的关系、你写的说明。
- 之后没有被改过。
- 记录的先后顺序。
- 所有记录都是用同一把签名钥匙签的。

**不能证明：**

- 是你本人想出来的。签名钥匙只代表「同一把钥匙」，不代表某一个人。
- 你是第一个想到的。
- 你为什么这样改。
- 内容是对的，或者有价值。

界面和报告里，每条信息都标明来源，三种永远分开显示：

| 来源 | 意思 |
| --- | --- |
| **Verified record**（可验证记录） | 有签名和时间证明，任何人都能自己检查。只说明记录当时已存在、之后没改过，不说明里面的话是真的。 |
| **Author statement**（作者陈述） | 你自己说的：「为什么」、关系、导入旧材料时填的更早日期、本机时钟时间。系统只能证明「你在那天这样说过」。 |
| AI 推断 | 第二版才有，v0.1 不产生。 |

两种时间证明也永远分开显示，不会合并成一个笼统的「已验证时间」：

| | **Date stamp**（日期章；报告里叫 Third-party timestamp，第三方签名时间证明） | **Public stamp**（公开章；报告里叫 Bitcoin anchor，比特币时间锚定） |
| --- | --- | --- |
| 协议 | RFC 3161，默认 [FreeTSA](https://freetsa.org/)，连不上时用 [DigiCert](https://www.digicert.com/) | [OpenTimestamps](https://opentimestamps.org/) |
| 多久拿到 | 几秒，显示「Date stamp ✓」 | 先「Public stamp: waiting」，通常几小时后「Public stamp: done」 |
| 要相信谁 | 相信这家机构的私钥和时钟；它的签名任何人都能检查 | 不用相信任何机构，只依赖公开的比特币区块链 |

**只追加，不修改。** 已经留下证明的记录，任何人都不能改，包括你自己。后来补一个关系、标一个里程碑、补一句说明、更正、撤回，都是新加的一条记录，有自己的签名和时间证明，界面上会显示「这是某天补加的」。

## 下载安装（不用装开发工具）

给不写代码的人：下载一个安装包，双击就能用。程序叫 **Research History**，自带 Python 和界面，不需要再装别的。

| 系统 | 安装包 |
| --- | --- |
| macOS 11 或更新，Apple 芯片（M1/M2/M3/M4） | `ResearchHistory-<版本>-macos-arm64.dmg` |
| Windows 10（1809 或更新）/ Windows 11，64 位 | `ResearchHistory-<版本>-windows-x64-setup.exe` |

安装包在本仓库的 **Releases** 页面（打版本标签时自动生成草稿，发布后别人才能下载），每次推送代码后也会在 **Actions → Package → Artifacts** 里生成一份（要登录 GitHub，保留 90 天）。Intel 芯片的 Mac 暂时没有安装包，可以先用下面「从源代码运行」的方法。

**用起来：** 双击打开后，程序在后台启动，并自动在浏览器里打开 http://127.0.0.1:8765 （8765 被占用时换下一个端口）。Mac 的菜单栏、Windows 右下角的通知区域里会出现一个蓝色圆形图标：点它可以重新打开页面，或者 **Quit** 退出。关掉浏览器窗口不会退出程序；要再打开页面，点这个图标 → **Open Research History**（Windows 上再双击一次程序也行）。程序不会同时开两份（安装版和 `make run` 也不会同时用同一个数据文件夹）。日志在数据文件夹的 `logs/app.log`。

**数据放在哪里：** Mac 是 `~/.rprov`，Windows 是 `%USERPROFILE%\.rprov`（和从源代码运行时是同一个位置，两种方式可以互换）。**升级**就是用新版本安装包再装一次；**卸载**（Mac：把程序拖进废纸篓；Windows：设置 → 应用 → Research History → 卸载）都不会删除数据。

### 第一次打开：系统会拦一下（安装包还没有签名）

这两个安装包暂时没有经过苹果和微软的签名，所以第一次打开时系统会提示「无法验证开发者」。确认安装包是从本仓库下载的，再按下面放行，以后就不会再问。

**macOS 14 及更早：** 把 Research History 拖进「应用程序」文件夹，在访达里**按住 Control 点它（或右键）→ 打开**，在弹出的对话框里再点 **打开**。

**macOS 15（Sequoia）及更新：** 右键打开这一招已经没有用了。先双击一次（会提示无法打开，点「完成」），然后打开 **系统设置 → 隐私与安全性**，往下拉到「安全性」，在「已阻止使用 Research History」旁边点 **仍要打开**，在弹出的对话框里再点 **仍要打开**，输入登录密码。

Mac 上第一次存签名钥匙时会问能否使用钥匙串，点 **始终允许**。因为没有签名，**每次升级后**系统还会再问一次，同样点「始终允许」——这是正常的，钥匙还在钥匙串里。

**Windows：** 双击安装包，如果出现蓝色的「Windows 已保护你的电脑」（SmartScreen），点 **更多信息 → 仍要运行**。用 Edge 下载时如果提示「通常不会下载此文件」，点「…」→ **保留** → **仍然保留**。安装不需要管理员权限，装在 `%LOCALAPPDATA%\Programs\Research History`，开始菜单里会有 Research History（桌面图标可选）。新装的 Windows 11 如果开着**智能应用控制（Smart App Control）**，可能会直接阻止没有签名的程序且没有「仍要运行」按钮；这时只能在 Windows 安全中心里把它关掉（关掉后可能无法再打开），或者等以后有签名的版本。签名钥匙存在 **Windows 凭据管理器**里。

### 在中国大陆等地方使用

两种时间证明都要连到国外的公开服务：日期章用 FreeTSA（连不上时自动改用 DigiCert），公开章用 4 个 OpenTimestamps 服务器，核对比特币区块用 blockstream.info 和 mempool.space。有些地方其中一部分可能被拦或者很慢。

- **Settings → Check stamp services…** 点 **Check now**，会逐个试一遍这些服务，并用一句话告诉你：日期章能不能拿到（由哪家给的）、公开章能不能开始、比特币区块能不能核对。试的时候只发送一个随机的测试值，不发送你的任何内容。
- **连不上也不会丢东西。** 步骤照样马上存在你的电脑上，缺的时间证明以后自动补上（每小时重试一次，也可以点 **Settings → Check stamps now**）。某个服务刚连不上时，接下来 10 分钟里保存不会再等它，所以不会每存一步都卡十几秒。
- 换一个网络（比如手机热点）再点一次 Check now，可以看出是不是当前网络的问题。

## 从源代码运行（开发者，Mac）

需要：[uv](https://docs.astral.sh/uv/)（自动准备 Python 3.12 或 3.13）、Node.js 22 或更新、`make`、OpenSSL 3（手工验证签名用，`brew install openssl@3`；若系统里还有更新版本的 openssl，请让 3 版排在前面）。

Windows 上也可以从源代码运行（没有 `make` 时直接用 `uv sync --extra ots --extra desktop`、`cd web; npm ci; npm run build`、`uv run python -m app.desktop`），数据在 `%USERPROFILE%\.rprov`。

```bash
git clone <本仓库地址> research-provenance-platform
cd research-provenance-platform
make install          # Python 依赖（uv.lock）和界面依赖（package-lock.json）
make freetsa-certs    # 第一次：从 freetsa.org 核对并更新内置的 FreeTSA 证书，并核对内置的 DigiCert 根证书（见 DECISIONS D-004、D-045）
make run              # 打开 http://127.0.0.1:8765
```

第一次打开分两步：

1. 填你的名字或笔名（报告里标为「自我声明」）和研究项目名，点 **Start**。程序生成签名钥匙并存进系统的钥匙保管处（macOS 钥匙串；Windows 凭据管理器），不以明文文件存放。
2. **打开自动备份**：选一个备份文件夹，设一个备份密码。之后每加一步、每拿到一个时间证明，程序都会自己往那里写一份新的备份（保留最近 10 份），不用再管。

![第一次打开：自动备份](docs/screenshots/first-run-backup.png)

**备份放哪儿？** 放一个「不只在这台电脑上」的地方：外接硬盘，或者你本来就在用的同步文件夹（Mac：iCloud Drive、Dropbox、Google Drive、OneDrive；Windows：OneDrive、iCloud for Windows 的 iCloud Drive、Dropbox、Google Drive 的「我的云端硬盘」、另一块硬盘或 U 盘）。程序会把找到的这类位置列出来让你选；如果你选的文件夹和数据在同一块硬盘上，顶栏会提醒「Backup is on this Mac only」——这样的备份在电脑丢了或坏了时帮不上忙。备份用的是你自己的存储，本工具不收费，也不经手。

**备份是全加密的**（`.rprovbackup` 文件：数据库、全部附件和签名钥匙一起用 AES-256-GCM 加密，打开它要备份密码或恢复码）：放在 iCloud 或 Dropbox 里，对方也看不到任何标题或内容。**请把备份密码记在安全的地方**——密码和恢复码都没有了，谁都打不开备份，包括我们。这台 Mac 把密码存在钥匙串里，所以备份能自动进行；只有恢复时才需要你再输入。

**恢复码：忘了密码也能打开。** 打开自动备份时，程序会显示一次**恢复码**（24 个字母和数字，分 4 组），可以直接点 Print 打印。忘了备份密码时，用恢复码一样能打开备份。程序自己不保存恢复码（只留一把由它算出的公钥），所以请打印或抄下来，和电脑分开放，也别放在备份文件夹里。丢了可以在 **Backup** 里重新生成一个（旧的仍能打开以前的备份）。打印页上还印着你的**签名钥匙指纹**（16 位）：用恢复码恢复后，程序会显示它恢复出来的钥匙指纹，两个必须一样，不一样就说明这份备份不是你的，别用。

**选文件夹时会马上提示它在哪儿**：iCloud Drive / Dropbox（✓ 电脑丢了也还在）、另一块硬盘（✓），还是「This Mac's own disk」（⚠ 电脑丢了这份备份也会一起丢）。备份文件夹不能放在程序自己的数据文件夹里。**正在使用的数据（`~/.rprov`）不要放进 iCloud 或 Dropbox**——同步可能把正在用的数据库弄坏；只有加密的备份文件放进去。如果你把数据文件夹放进了同步文件夹，页面顶部会一直提醒。

**电脑坏了或丢了怎么办？** 在新 Mac 上装好本工具，第一次打开时选 **Restore from a backup**，选最新的 `.rprovbackup` 文件、输入备份密码（忘了密码就点「Forgot the password? Use the recovery code instead」，输入恢复码）。研究步骤、附件、时间证明和签名钥匙都会原样回来，验证结果和原来一致，新记录仍属于同一身份；恢复以后**自动备份先暂停**，顶栏显示「Backup paused — confirm to resume」：确认这台就是以后要用的 Mac，再点 **Resume automatic backup to this folder**（如果旧 Mac 还在往同一个文件夹备份，就选别的文件夹）。用「迁移助理」或 Time Machine 把整台电脑搬过去也一样：程序会认出这是一份复制过来的数据，先暂停自动备份，等你确认。**只用一台 Mac 记录**：如果新旧两台都开着程序、往同一个备份文件夹写，两边都会显示「Another Mac is backing up here too」和红色横条——请把不用的那台上的程序关掉，否则两边各记各的，历史会分叉，以后恢复只能拿回其中一边。用恢复码恢复的话，程序不知道原来的密码，会请你设一个新密码。顶栏的备份按钮随时显示状态（上次备份时间、失败原因），点它可以立刻再备份、换文件夹或换密码，也可以单独下载一份备份文件。

**演练一次恢复（推荐，在同一台 Mac 上也安全）**：用一个临时文件夹，并让副本完全不碰钥匙串：

```bash
RPROV_HOME=~/.rprov-restore-test RPROV_KEYSTORE=memory make run PORT=8767
```

打开 http://127.0.0.1:8767，选 **Restore from a backup**，选备份文件夹里最新的 `.rprovbackup`，用恢复码恢复，看记录是否都在。副本里**不要点 Resume，也不要加步骤**；看完关掉它，删除 `~/.rprov-restore-test`（注意别删成 `~/.rprov`）。

注意：时间证明服务（FreeTSA、比特币）只收到每一步的「指纹」（哈希），从指纹看不出也恢复不出内容——所以它们也不能把你的内容还给你，比特币也不能。能把内容找回来的只有备份。**Settings → Where is my data?**（页面底部也有） 里有同样的说明。

只想单独备份签名钥匙：**Settings → Back up signing key only…**（完整备份里已经包含钥匙）。

**先练习，再记正式的。** 记录一旦存下就删不掉，所以页面顶部有一个开关：**My research**（正式记录）/ **Practice**（练习空间）。练习空间是完全分开的另一套数据和签名钥匙（放在 `~/.rprov/practice/`），顶栏变成橙色，并一直显示「Practice: nothing here goes into your real record」；在那里保存直接存，按钮写 **Save practice step**。练习空间不备份，可以在 **Settings → Start practice over…** 清空重来，或者 **Fill practice with sample research** 放进虚构的 FSF 样例随便看。第一次打开时也可以先点「Open the practice space」。

**存进正式记录前会再确认一次。** 在 My research 里点 **Save step**，会弹出「Save this step to your real record?」，列出类型、标题、正文开头、附件、和哪一步有关、你写的原因，提醒「存进去以后不能修改也不能删除，只能补充或撤回」。点 **Save to my record** 才真正存入，点 **Go back** 回去接着改。后来补关系、标关键一步、补说明、撤回，也都会先确认。从练习切回正式记录时会提醒一次。

**想在命令行里另开一份样例？** `make demo && make run` 会把虚构的 FSF 样例（14 条记录，9 种类型，3 种关系，里程碑、后来补加的关系、补充说明、L1/L2 导入、撤回）载入一个空的数据目录。记录不能删除，所以开始记真实材料之前，把样例挪开：`mv ~/.rprov ~/.rprov-demo`（以后用 `RPROV_HOME=~/.rprov-demo make run` 再看样例）。也可以一开始就 `RPROV_HOME=~/.rprov-demo make demo`。

数据都在 `~/.rprov/`（权限 0700）。原文、附件、标题、说明都不离开本机；对外只发送时间证明所需的哈希（记录 ID），时间证明服务能看到请求的 IP 地址和时间。没有账号，没有我们的云服务，没有任何统计或崩溃上报。自动备份只是往你选的本地文件夹里写一个加密文件；如果那个文件夹被你自己的 iCloud / Dropbox 同步，离开电脑的也只是这个打不开的加密文件（见 DECISIONS D-033）。

## 中文 / English

界面右上角（第一次打开时在欢迎页上）有一个 **中文 / English** 按钮，点一下整个界面就换成另一种语言；第一次打开时跟着浏览器的语言走。选择会被记住，菜单栏 / 托盘图标的菜单也跟着换。

- **只翻译程序自己的文字。** 你写的标题、正文、说明、理由照原样显示，从不翻译。
- **报告可以选语言。** 导出时有「报告语言」一项，默认和界面一样：`report.html` 和 `VERIFY.md` 都有中文版。`verify.py` 的输出和失败代码一直是英文（它是给任何读者用的同一个检查程序）。
- **Windows 安装程序**在中文 Windows 上显示中文，其他系统上显示英文。

下面的说明用英文界面的按钮名，中文界面里是对应的中文，例如 **+ Add a step** =「+ 记一步」，**Share** =「分享」。

## 怎么用

1. **新建研究项目**，比如「FSF」。
2. **+ Add a step**（空项目里也可以直接点「想法」「实验」等卡片）：选类型（想法、笔记、论断/假设、文档、代码、实验、数据、图、发表），写标题和正文（Markdown），或拖入文件。
   - 代码可以只填仓库地址和提交编号，但这只是外部引用：仓库以后删了就拿不回那份代码。想保留代码内容，同时附上 `git archive` 打包文件。
   - 发表的论文填 DOI 或网址（第三方参考，L2）。
3. **+ Connect to an earlier step**：说明它和之前哪一步有关——新版本（revises）、从它发展出来（derived from）、用到了它（uses）。可以写一句「为什么」，显示为作者陈述；重要的可以勾「Mark as a key step」（关键一步）。
4. 点 **Save step**。几秒内显示「Date stamp ✓」，几小时后显示「Public stamp: done」。每个词旁边有一个小「?」，点开是一句话的解释。
5. **放进旧材料**时勾选「This is older material I'm adding now」：只能证明「记进来的那天已经存在」，你填的更早日期显示为作者陈述（L1），有 DOI、邮件、网页存档等外部记录的标 L2。
6. **看地图**（Map）：按记录顺序从左到右、按类型分行，箭头从旧记录指向新记录；看不懂图上的线和 D/P 图标，点 Map 旁边的「?」。**List** 是按日期排的清单，**Key steps only** 只看关键的几步。点任何一步，看它的内容、两种时间证明、作者说明和后来补加的东西；记录 ID、哈希、签名收在「Technical details」里。顶栏的数字只数研究步骤，不数第一条「创世」记录和后来补加的关系、说明。

![记录详情](docs/screenshots/detail.png)

### 少动手：快速记一笔、盯住文件夹、从 git 自动记录

- **快速记一笔（Quick note）**：顶栏的按钮，或者菜单栏 / 托盘图标菜单里的「Quick note…」（快速记一笔…）。只有一个输入框：第一行是标题，后面是正文，点保存（或 ⌘/Ctrl+Enter）就存成一条笔记，照样拿时间章。
- **盯住一个文件夹（Settings → Watch a folder…）**：选一项工作的文件夹（草稿、数据、图）和项目。里面的文件新出现或被改过、并且两分钟没再变，就当作一个新版本：
  1. 当场给它的指纹盖日期章（只发出哈希），复制一份放进**收件箱**——这时还**不在**正式记录里。
  2. 顶栏出现「Inbox (n)」（收件箱）。值得留下的点「Record as a step」（记成一步）：标题、类型、「新版本」关系都已经填好；不要的点「Throw away」（丢掉），什么都不留下。
  3. 记成的那一步带着收件时的日期章（文件旁边的 `<文件名>.tsr`），所以时间不吃亏：报告、`verify.py` 和 `VERIFY.md` 里的 `openssl` 命令都能核对「这个文件在收件时已经存在」。
  - 跳过隐藏文件、Office 和编辑器的锁文件与临时文件、`.git` 等文件夹，以及超过 50 MB 的文件；文件夹里超过 2000 个文件时会拒绝（多半选错了文件夹）。
  - 收件箱里的副本只在本机的数据文件夹里，不进备份；记成一步以后才和其他步骤一样进入记录和备份。
- **从 git 自动记录（Settings → Record from git…）**：选一个本机的 git 仓库文件夹和分支，之后这个分支上**每一次新提交**都会自动变成地图上的一个「代码」步骤：标题和正文来自提交说明，外部引用是这次提交，并且「修改自」上一次提交的那一步。程序运行时每分钟看一次，下次启动时补上中间的提交（一次超过 20 个就合成一步列出来）。
  - 只读取本机的仓库：不拉取、不推送，也不连 GitHub；离开电脑的仍然只有时间章需要的指纹。需要电脑上装有 git。
  - 可以顺便把以前的历史补记进来：按标签分段，没有标签就按月（太久就按年），每段一步。**git 显示的日期只是作者陈述**（可以被改），所以这些步骤标为「补记的旧材料」，日期显示为声称日期（L1），不算已验证的时间；同样，比今天早的提交日期也只当作者陈述。
  - 可选「每一步都保存一份代码（zip）」：这样即使仓库被删或改写也能核对代码，但每次提交都存一份整个仓库（每份最多 50 MB）。不保存的话，只记下是哪一次提交，界面会标明「外部引用，未保存代码内容」。
  - 打了标签（tag）的提交会自动标成关键一步；后来才打的标签，会作为一次「后来补加」把那一步标成关键一步。你取消的标记不会被再次加上。
  - 在「我的研究」里，每一次被记下的提交都是永久的一步。随时可以「停止记录」，已经记下的步骤保留。

### 研究经过（Story）：不用 AI，自动讲出来

地图旁边的 **Story**（研究经过）标签：按记录的先后，用固定句式把每一步和后来补加的内容写成段落，例如「2026-05-03，作者记下了一个实验：“Numerical experiment 1”。作者注明它用到了“Formula v1”。」

- **不用 AI，不加东西。** 每一句都来自记录本身；「为什么」只在你自己写过原因的地方出现，原样引用。
- **每段都标出来源：** 记录编号和日期，带 ✓ 的是日期章的时间，点一下就打开那一步。你自己的陈述（原因、说明、声称的日期，以及步骤之间的关系）用颜色标出来。
- **分段：** 每到一个关键步就结束一部分；没有关键步时按月分。
- **带走：** 可以存成 Markdown，或者打印成 PDF。分享的报告（`report.html`）里也有这一节，而且只写证据包里公开的内容：「只证明存在」的记录只写「第 n 条记录没有公开」。
- 中英文都有，跟着界面语言；报告跟着导出时选的报告语言。

## 发给别人：导出证据包

点 **Share**，逐条选择公开多少：

| 公开程度 | 读者能看到 |
| --- | --- |
| Everything（全部公开） | 全部内容 |
| Structure only（只公开结构） | 类型、标题、关系、作者说明、时间；看不到正文（但能看到正文和附件的哈希） |
| Existence only（只证明存在） | 「第 n 条记录最迟在某时已存在」 |

导出前会逐条预览将被公开的内容。注意两点：「只公开结构」会公开正文和附件的哈希，别人已经拿到或容易猜到的内容可能被拿来对照确认；证据包里的 `chain.json` 会显示到最后一条导出记录为止一共有多少条记录。

证据包是一个 zip：

```text
report.html     网页报告，断网也能打开，可用浏览器打印成 PDF
verify.py       独立检查程序
VERIFY.md       手工验证步骤（sha256sum / openssl / ots 命令）
manifests/ payloads/ content/ signatures/ proofs/ certs/ identity/ chain.json bundle.json
```

![报告](docs/screenshots/report.png)

## 怎么验证（读者）

对方不用装这个工具，也不用相信你或我们：

```bash
pip install "cryptography>=44" "rfc3161-client>=1.0.6"
python3 verify.py provenance-FSF-2026-10-12.zip      # 也可以对解压后的目录运行
```

检查比特币时间锚定时，`verify.py` 会向两个公开区块浏览器（blockstream.info、mempool.space）查询区块头，只发送区块高度；有自己的比特币节点可以用 `--bitcoin-node http://user:pass@127.0.0.1:8332`，完全不联网用 `--offline`（这时比特币锚定显示为「未核对」，不算失败也不给时间）。

它逐条检查：内容的哈希（V1）、清单和载荷（V2）、签名（V3）、第三方签名时间证明（V4，对照内置的 FreeTSA 和 DigiCert 两个根证书，最后会打印两者的指纹）、比特币时间锚定（V5）、日志链（V6）、引用（V7）。每条记录的结果是 *Pass*、*Pass (Bitcoin anchor pending)*、*Warning* 或 *Fail*（附失败代码）。退出码 0 表示没有任何记录失败。

不想运行程序的人，可以照 `VERIFY.md` 用 `sha256sum`、`openssl` 和 `ots` 命令手工检查同样的内容。

## 开发

```bash
make dev              # 后端（自动重载）+ Vite 开发服务器 http://127.0.0.1:5173
make test             # ruff + 全部测试（单元、接口、篡改、端到端）；联网测试跳过
make test-network     # 需要真实 FreeTSA / DigiCert / OpenTimestamps / 区块浏览器的测试（含 AC-09），在联网的 Mac 上跑
make verify-py        # 从核心库重新生成 dist/verify.py
make tsa-fixture      # 把真实的 FreeTSA / DigiCert 回应存成离线测试用的样本（在联网的 Mac 上跑，存进 tests/fixtures/tsa/ 后提交）
```

不联网开发时可以用模拟时间证明：`RPROV_TSA=mock RPROV_BTC=mock make run`（模拟机构签的证明，`verify.py` 默认不信任；只在测试时加 `--tsa-root certs/mock-tsa-root.pem`）。没有钥匙串的 Linux 开发环境另需 `RPROV_KEYSTORE=dev-insecure-file`（明文钥匙文件，只用于开发）。

**打安装包**（DECISIONS D-044）：

```bash
bash packaging/build_macos.sh          # 在 Mac 上：dist/Research History.app 和 .dmg，并自动做一遍冒烟测试
# Windows（需要 Inno Setup 6）：
#   ./packaging/build_windows.ps1; ./packaging/smoke_windows.ps1
```

GitHub Actions 的 **Package** 工作流在每次推送时自动打两个安装包，并完整试一遍（安装、启动、建身份、存一步、导出、用导出的 verify.py 检查、卸载后数据还在）。发布新版本：把 `pyproject.toml` 里的 `version` 改成新版本号并提交，再推送同名标签（如 `git tag v0.2.0 && git push origin v0.2.0`），工作流会建一个附带两个安装包和 `SHA256SUMS.txt` 的**草稿** Release，检查无误后在 GitHub 上点发布。在中国大陆下载 GitHub 可能很慢，可以把同样的文件另外放到国内网盘或对象存储，并附上 `SHA256SUMS.txt` 让大家对照。

**以后要签名的话需要什么：**

- **macOS**：加入 Apple Developer Program（每年 99 美元），申请「Developer ID Application」证书；打包时用它签名（开启 hardened runtime），再用 `xcrun notarytool submit --wait` 提交苹果公证、`xcrun stapler staple` 把结果钉进 .dmg。之后用户双击就能打开，升级后钥匙串也不会再问。证书和 App Store Connect API 密钥可以存成 GitHub Secrets，让 Package 工作流自动签名和公证。
- **Windows**：需要代码签名证书。可选：微软的云签名服务（Azure Trusted Signing，现名 Artifact Signing，约每月 10 美元，目前只对部分国家和地区的机构与个人开放，以微软官网为准），或者向证书机构购买 OV 代码签名证书（每年约 200–500 美元，私钥必须放在硬件令牌或云端 HSM 里）。用 `signtool` 签安装包和程序，并加时间戳（如 `http://timestamp.digicert.com`）。签名后「仍要运行」的提示会随着下载量逐渐消失（SmartScreen 信誉要积累，EV 证书现在也不能立刻免除提示），智能应用控制也会放行。
- **Intel Mac**：在 Intel 的 macOS 运行器上再打一份（`macos-13`），或者用 universal2 的 Python 和依赖打一个同时支持两种芯片的包；代码本身不用改。

代码结构：`core/provenance_core/` 是唯一包含信任逻辑的核心库（JCS、哈希、签名、日志链、重放、验证、时间证明接口），`app/` 是本地服务（FastAPI + SQLite），`web/` 是界面（React + TypeScript），`tools/build_verify.py` 从核心库生成单文件 `verify.py`。

## 当前进度

- **P0 已完成**：只追加的记录、签名、重放；第三方签名时间证明（RFC 3161）；导出证据包、`report.html`（含静态演化图）、`verify.py`、篡改测试；记录表单和演化图。
- **P1 已完成**：比特币时间锚定（OpenTimestamps）和区块浏览器核对；「只看里程碑」视图；时间线视图；详情侧栏的完整分区（Verified record / Author statement / Later additions / Changes，以及在侧栏里追加关系、里程碑、说明、撤回）；备份与恢复；FSF 样例数据。
- **第 4 轮（安装包）**：macOS（Apple 芯片）和 Windows 10/11 安装包，菜单栏/通知区域图标，只开一份；Windows 的备份位置建议和全套测试（含浏览器测试）在 GitHub Actions 上跑；日期章增加 DigiCert 作为备用；Settings → Check stamp services 检查各个时间证明服务能不能连上（见 DECISIONS D-043 – D-045）。
- **第 5 轮（进行中）**：中英文切换——界面、程序自己写的文字和错误提示、导出的报告和 VERIFY.md、菜单栏 / 托盘菜单、Windows 安装程序（见 DECISIONS D-046）；快速记一笔、从本机 git 仓库自动记录提交（D-047）；不用 AI 的「研究经过」（D-048）；盯住文件夹和收件箱（D-049）。
- **需要在联网的 Mac 上完成**：`make freetsa-certs`、`make test-network`（AC-09：真实 FreeTSA 的 `.tsr` 用 `openssl ts -verify` 验证；真实 DigiCert 时间戳；真实 OpenTimestamps 日历和区块浏览器），以及 PRD 第 16 节的 4 项人工检查。
