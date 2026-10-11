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
| 协议 | RFC 3161，默认 [FreeTSA](https://freetsa.org/) | [OpenTimestamps](https://opentimestamps.org/) |
| 多久拿到 | 几秒，显示「Date stamp ✓」 | 先「Public stamp: waiting」，通常几小时后「Public stamp: done」 |
| 要相信谁 | 相信这家机构的私钥和时钟；它的签名任何人都能检查 | 不用相信任何机构，只依赖公开的比特币区块链 |

**只追加，不修改。** 已经留下证明的记录，任何人都不能改，包括你自己。后来补一个关系、标一个里程碑、补一句说明、更正、撤回，都是新加的一条记录，有自己的签名和时间证明，界面上会显示「这是某天补加的」。

## 安装（Mac）

需要：[uv](https://docs.astral.sh/uv/)（自动准备 Python 3.12 或 3.13）、Node.js 22 或更新、`make`、OpenSSL 3（手工验证签名用，`brew install openssl@3`；若系统里还有更新版本的 openssl，请让 3 版排在前面）。

```bash
git clone <本仓库地址> research-provenance-platform
cd research-provenance-platform
make install          # Python 依赖（uv.lock）和界面依赖（package-lock.json）
make freetsa-certs    # 第一次：从 freetsa.org 核对并更新内置的 FreeTSA 证书（见 DECISIONS D-004）
make run              # 打开 http://127.0.0.1:8765
```

第一次打开分两步：

1. 填你的名字或笔名（报告里标为「自我声明」）和研究项目名，点 **Start**。程序生成签名钥匙并存进 macOS 钥匙串，不以明文文件存放。
2. **打开自动备份**：选一个备份文件夹，设一个备份密码。之后每加一步、每拿到一个时间证明，程序都会自己往那里写一份新的备份（保留最近 10 份），不用再管。

![第一次打开：自动备份](docs/screenshots/first-run-backup.png)

**备份放哪儿？** 放一个「不只在这台 Mac 上」的地方：外接硬盘，或者你本来就在用的同步文件夹（iCloud Drive、Dropbox、Google Drive、OneDrive）。程序会把找到的这类位置列出来让你选；如果你选的文件夹和数据在同一块硬盘上，顶栏会提醒「Backup is on this Mac only」——这样的备份在电脑丢了或坏了时帮不上忙。备份用的是你自己的存储，本工具不收费，也不经手。

**备份是全加密的**（`.rprovbackup` 文件：数据库、全部附件和签名钥匙一起用 AES-256-GCM 加密，打开它要备份密码或恢复码）：放在 iCloud 或 Dropbox 里，对方也看不到任何标题或内容。**请把备份密码记在安全的地方**——密码和恢复码都没有了，谁都打不开备份，包括我们。这台 Mac 把密码存在钥匙串里，所以备份能自动进行；只有恢复时才需要你再输入。

**恢复码：忘了密码也能打开。** 打开自动备份时，程序会显示一次**恢复码**（24 个字母和数字，分 4 组），可以直接点 Print 打印。忘了备份密码时，用恢复码一样能打开备份。程序自己不保存恢复码（只留一把由它算出的公钥），所以请打印或抄下来，和电脑分开放，也别放在备份文件夹里。丢了可以在 **Backup** 里重新生成一个（旧的仍能打开以前的备份）。

**选文件夹时会马上提示它在哪儿**：iCloud Drive / Dropbox（✓ 电脑丢了也还在）、另一块硬盘（✓），还是「This Mac's own disk」（⚠ 电脑丢了这份备份也会一起丢）。备份文件夹不能放在程序自己的数据文件夹里。**正在使用的数据（`~/.rprov`）不要放进 iCloud 或 Dropbox**——同步可能把正在用的数据库弄坏；只有加密的备份文件放进去。如果你把数据文件夹放进了同步文件夹，页面顶部会一直提醒。

**电脑坏了或丢了怎么办？** 在新 Mac 上装好本工具，第一次打开时选 **Restore from a backup**，选最新的 `.rprovbackup` 文件、输入备份密码（忘了密码就点「Forgot the password? Use the recovery code instead」，输入恢复码）。研究步骤、附件、时间证明和签名钥匙都会原样回来，验证结果和原来一致，新记录仍属于同一身份；如果新 Mac 上也能看到同一个备份文件夹，自动备份会接着进行。顶栏的备份按钮随时显示状态（上次备份时间、失败原因），点它可以立刻再备份、换文件夹或换密码，也可以单独下载一份备份文件。

注意：时间证明服务（FreeTSA、比特币）只收到每一步的「指纹」（哈希），从指纹看不出也恢复不出内容——所以它们也不能把你的内容还给你，比特币也不能。能把内容找回来的只有备份。**Settings → Where is my data?**（页面底部也有） 里有同样的说明。

只想单独备份签名钥匙：**Settings → Back up signing key only…**（完整备份里已经包含钥匙）。

**先练习，再记正式的。** 记录一旦存下就删不掉，所以页面顶部有一个开关：**My research**（正式记录）/ **Practice**（练习空间）。练习空间是完全分开的另一套数据和签名钥匙（放在 `~/.rprov/practice/`），顶栏变成橙色，并一直显示「Practice: nothing here goes into your real record」；在那里保存直接存，按钮写 **Save practice step**。练习空间不备份，可以在 **Settings → Start practice over…** 清空重来，或者 **Fill practice with sample research** 放进虚构的 FSF 样例随便看。第一次打开时也可以先点「Open the practice space」。

**存进正式记录前会再确认一次。** 在 My research 里点 **Save step**，会弹出「Save this step to your real record?」，列出类型、标题、正文开头、附件、和哪一步有关、你写的原因，提醒「存进去以后不能修改也不能删除，只能补充或撤回」。点 **Save to my record** 才真正存入，点 **Go back** 回去接着改。后来补关系、标关键一步、补说明、撤回，也都会先确认。从练习切回正式记录时会提醒一次。

**想在命令行里另开一份样例？** `make demo && make run` 会把虚构的 FSF 样例（14 条记录，9 种类型，3 种关系，里程碑、后来补加的关系、补充说明、L1/L2 导入、撤回）载入一个空的数据目录。记录不能删除，所以开始记真实材料之前，把样例挪开：`mv ~/.rprov ~/.rprov-demo`（以后用 `RPROV_HOME=~/.rprov-demo make run` 再看样例）。也可以一开始就 `RPROV_HOME=~/.rprov-demo make demo`。

数据都在 `~/.rprov/`（权限 0700）。原文、附件、标题、说明都不离开本机；对外只发送时间证明所需的哈希（记录 ID），时间证明服务能看到请求的 IP 地址和时间。没有账号，没有我们的云服务，没有任何统计或崩溃上报。自动备份只是往你选的本地文件夹里写一个加密文件；如果那个文件夹被你自己的 iCloud / Dropbox 同步，离开电脑的也只是这个打不开的加密文件（见 DECISIONS D-033）。

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

它逐条检查：内容的哈希（V1）、清单和载荷（V2）、签名（V3）、第三方签名时间证明（V4，对照内置的 FreeTSA 根证书）、比特币时间锚定（V5）、日志链（V6）、引用（V7）。每条记录的结果是 *Pass*、*Pass (Bitcoin anchor pending)*、*Warning* 或 *Fail*（附失败代码）。退出码 0 表示没有任何记录失败。

不想运行程序的人，可以照 `VERIFY.md` 用 `sha256sum`、`openssl` 和 `ots` 命令手工检查同样的内容。

## 开发

```bash
make dev              # 后端（自动重载）+ Vite 开发服务器 http://127.0.0.1:5173
make test             # ruff + 全部测试（单元、接口、篡改、端到端）；联网测试跳过
make test-network     # 需要真实 FreeTSA / OpenTimestamps / 区块浏览器的测试（含 AC-09），在联网的 Mac 上跑
make verify-py        # 从核心库重新生成 dist/verify.py
```

不联网开发时可以用模拟时间证明：`RPROV_TSA=mock RPROV_BTC=mock make run`（模拟机构签的证明，`verify.py` 默认不信任；只在测试时加 `--tsa-root certs/mock-tsa-root.pem`）。没有钥匙串的 Linux 开发环境另需 `RPROV_KEYSTORE=dev-insecure-file`（明文钥匙文件，只用于开发）。

代码结构：`core/provenance_core/` 是唯一包含信任逻辑的核心库（JCS、哈希、签名、日志链、重放、验证、时间证明接口），`app/` 是本地服务（FastAPI + SQLite），`web/` 是界面（React + TypeScript），`tools/build_verify.py` 从核心库生成单文件 `verify.py`。

## 当前进度

- **P0 已完成**：只追加的记录、签名、重放；第三方签名时间证明（RFC 3161）；导出证据包、`report.html`（含静态演化图）、`verify.py`、篡改测试；记录表单和演化图。
- **P1 已完成**：比特币时间锚定（OpenTimestamps）和区块浏览器核对；「只看里程碑」视图；时间线视图；详情侧栏的完整分区（Verified record / Author statement / Later additions / Changes，以及在侧栏里追加关系、里程碑、说明、撤回）；备份与恢复；FSF 样例数据。
- **需要在联网的 Mac 上完成**：`make freetsa-certs`、`make test-network`（AC-09：真实 FreeTSA 的 `.tsr` 用 `openssl ts -verify` 验证；真实 OpenTimestamps 日历和区块浏览器），以及 PRD 第 16 节的 4 项人工检查。
