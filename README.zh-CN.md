<h1 align="center">Codex App Provider Fork</h1>

<p align="center">
  <a href="README.md">English</a> |
  <strong>简体中文</strong>
</p>

<p align="center">
  <strong>通过新建 Codex 会话分支切换 Provider，并可选择修改持久默认配置。</strong>
</p>

<p align="center">
  <a href="skills/provider-fork/SKILL.md">
    <img alt="Codex Skill" src="https://img.shields.io/badge/Codex-Skill-2563eb?style=flat-square">
  </a>
  <a href="https://www.python.org/">
    <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-172554?style=flat-square">
  </a>
  <img alt="Transport" src="https://img.shields.io/badge/transport-App%20Server-0f8f88?style=flat-square">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-d97706?style=flat-square">
</p>

<p align="center">
  <a href="#为什么需要这个工具">背景</a>
  &middot;
  <a href="#支持的能力">功能</a>
  &middot;
  <a href="#切换模式">切换模式</a>
  &middot;
  <a href="#安装">安装</a>
  &middot;
  <a href="skills/provider-fork/SKILL.md">Skill 参考</a>
</p>

本项目提供 `provider-fork` Skill 和 Python 脚本，用于在已有官方登录、BeeAPI
和 Krill Code 之间切换。它在原生 fork 请求中显式指定目标 Provider，复制已完成
的会话历史，为新分支命名，再核对返回值和保存的 Provider 元数据。源会话保留，
脚本不会写入 `auth.json`，切换操作本身也不会发起推理。

默认的 **session** 模式不修改 `config.toml`。可选的 **persistent** 模式先创建并
验证 fork，再仅修改用户配置根部的 `model_provider`，供后续采用该默认值的会话使用。

## 为什么需要这个工具

修改全局 Provider 配置，不会立刻替换 App Server 已加载会话的 Provider。
为了切换而反复重启 App，也可能打断其他工作。

本工具通过原生 `thread/fork` 在新分支边界明确选择 Provider。已完成的历史被
保留，新分支得到独立名称，例如 `BeeAPI | Fix parser`。再次切到 Krill 时，
会替换已识别的前缀，得到 `Krill Code | Fix parser`。

底层使用 [Codex App Server 协议](https://developers.openai.com/codex/app-server)。
它是配置工具和 RPC 客户端，不代理模型推理流量。

## 支持的能力

| 能力 | 行为 |
| --- | --- |
| 按 Provider fork | 在已完成的历史边界创建显式指定 Provider 的新会话 |
| 单会话切换 | 创建 fork，不改变全局默认值 |
| 持久切换 | 验证 fork 后，最小化修改默认 Provider |
| 仅修改默认值 | 不创建会话，直接切换或恢复默认 Provider |
| 保留官方登录 | 不运行登录/退出命令，不写入 `auth.json` |
| 统一命名 | 用 `Official |`、`BeeAPI |` 或 `Krill Code |` 替换已有的已识别前缀 |
| 操作回执 | 返回 Provider 核对结果、源和新会话 ID、切换模式与推理状态 |
| 重试恢复 | 相同请求 ID 返回已验证回执，不重复 fork，也不重放旧的默认值修改 |
| 只读检查 | 查看默认配置和近期会话 ID |

支持的名称为 `official` / `openai`、`beeapi`、`krill` / `krill-code`。
第三方定义和凭据需要提前配置在目标 Codex 环境里。当前增加其他 Provider
需要扩展脚本的别名与名称表。

## 切换模式

| 模式 | 是否修改用户配置 | 结果 |
| --- | --- | --- |
| `fork --mode session`，默认 | 否 | 新会话保存目标 Provider |
| `fork --mode persistent` | 仅根部 `model_provider` | 已验证的 fork，以及供后续会话使用的新默认值 |
| `default` | 仅根部 `model_provider` | 修改默认值，不创建 fork |

修改默认值不会切换其他已加载会话。显式 profile、项目配置和模型/Provider
覆盖可能比用户默认值优先；持久模式不会删除这些覆盖。

### 重启之后会怎样？

在已验证的 Codex 版本中，普通恢复流程没有显式模型相关覆盖时，会恢复会话
保存的模型和 Provider。因此 session 模式创建的 BeeAPI 分支可以继续使用
BeeAPI，即使全局默认值仍然是官方。

显式模型/Provider 设置或选中的 profile 可能改变优先级。尤其是仅覆盖模型，
也可能使 App Server 采用当前默认 Provider。工具不会拦截 App 或 CLI 的恢复
请求；配置中仍需保留 Provider 定义。直接调用 RPC 恢复时，应指定
`modelProvider` 并核对最终生效值。

## 安装

需要 Python 3.11+ 和兼容的 Codex 可执行文件。只有 daemon 传输需要
`requirements.txt` 中的依赖。

### Linux / Unix

```bash
git clone https://github.com/xukp20/codex-app-provider-fork.git
cd codex-app-provider-fork
python -m pip install -r requirements.txt
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$PWD/skills/provider-fork" \
  "${CODEX_HOME:-$HOME/.codex}/skills/provider-fork"
```

使用链接安装后，运行 `git pull --ff-only` 即可更新仓库文件。

### Windows PowerShell

```powershell
git clone https://github.com/xukp20/codex-app-provider-fork.git
Set-Location codex-app-provider-fork
$codexDir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$skillsDir = Join-Path $codexDir 'skills'
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
Copy-Item -LiteralPath '.\skills\provider-fork' -Destination $skillsDir -Recurse
```

安装后重新加载 Skill 发现流程。复制安装需要在拉取仓库更新后单独同步文件。
如果已存在 `provider-fork`，请更新其中的文件，避免再次复制目录造成嵌套。

### Provider 配置

把定义合并到现有用户 `config.toml`，保留其余配置及官方登录。以下地址仅为
占位符，不是可直接使用的服务端点：

```toml
# 根部设置，放在所有 [table] 前。初始默认值保持官方。
model_provider = "openai"

[model_providers.beeapi]
name = "BeeAPI"
base_url = "https://YOUR-BEEAPI-ENDPOINT/v1"
wire_api = "responses"
requires_openai_auth = false
env_key = "BEEAPI_API_KEY"

[model_providers.krill-code]
name = "Krill Code"
base_url = "https://YOUR-KRILL-ENDPOINT/v1"
wire_api = "responses"
requires_openai_auth = false
env_key = "KRILL_CODE_API_KEY"
```

在 App Server 启动时继承的环境中，分别设置第三方自己的密钥。只在新终端里
设置变量，不会更新已经运行的 daemon 的环境。现有 `experimental_bearer_token`
配置也支持，但包含明文秘密，必须保持私密；不要填入官方登录 token。
另见 [Codex 配置参考](https://developers.openai.com/codex/config-reference)。

## 使用

可以直接对 Codex 说：

> 使用 $provider-fork，把这个会话 fork 到 BeeAPI，保持全局默认值不变。

> 使用 $provider-fork，把 THREAD_ID fork 到 Krill，并把 Krill 设为持久默认值。

> 使用 $provider-fork，把默认 Provider 恢复为官方。

也可以在仓库根目录直接运行：

```bash
python skills/provider-fork/scripts/provider_fork.py status
python skills/provider-fork/scripts/provider_fork.py list --limit 30
python skills/provider-fork/scripts/provider_fork.py fork \
  --thread THREAD_ID --provider beeapi --mode session --request-id bee-switch-001
python skills/provider-fork/scripts/provider_fork.py fork \
  --thread THREAD_ID --provider krill --mode persistent --request-id krill-switch-001
python skills/provider-fork/scripts/provider_fork.py default --provider official
```

每个新操作使用新的请求 ID，仅在恢复同一次操作时复用。`--model` 指定目标
支持的模型，否则保留源模型。`--last-turn` 指定已完成的历史边界，否则使用
服务器返回的最后一个已完成 turn。

核对 `verified: true`、目标 Provider 和新 `threadId`。持久模式还需
`persistentApplied: true`。退出码 `2` 表示 fork 已验证，但修改默认值失败；
先检查回执和当前配置，再单独修改默认值。

创建 fork 只确认 Provider 元数据，不证明目标一定能够继续所有继承的历史。
准备好后在 Codex 中继续新会话；切换本身不启动模型 turn。通过返回的 ID
打开新会话，确认 App 可读取；可见性和侧栏实时刷新取决于 App 版本。

### 传输选择

| 传输 | 行为 |
| --- | --- |
| Windows 上的 `auto` | 使用同一个 `CODEX_HOME` 启动临时 stdio App Server |
| 其他平台上的 `auto` | 连接已有 daemon 的 Unix 控制 socket |
| `--transport stdio` | 使用临时子进程，需要兼容的 Codex 可执行文件 |
| `--transport daemon` | 使用已有 Unix socket，需要 `websockets` |

传输参数放在**子命令之前**。daemon socket 为
`${CODEX_HOME:-$HOME/.codex}/app-server-control/app-server-control.sock`。
设置 `CODEX_PROVIDER_CLI` 可覆盖可执行文件发现；Windows 先查找 App 自带的
可执行文件，再查 `PATH`，其他平台使用 `PATH`。

独立 stdio 进程不能接管被其他 writer 持有的会话。遇到写入锁时，应检查
所属服务器并采用其可用传输。工具不会为了释放锁重启 App 或 daemon。

## 安全边界

- 不写入 `auth.json`，不复制官方 token，不直接编辑会话 JSONL/SQLite，
  不退出登录，不修改源会话的 Provider。
- 切回官方时拒绝根部 `openai_base_url` 和 `OPENAI_BASE_URL` 覆盖。第三方
  切换拒绝非 HTTPS 地址、要求官方认证的定义和缺少 Provider 凭据设置的
  定义。检查范围是读取的用户配置与脚本环境，不涵盖所有外部配置层或网络代理。
- 持久修改保留其他 TOML 值、支持的格式和文件权限。原配置备份位于
  `$CODEX_HOME/provider-fork/backups/`，可能含有密钥，应保持私密。
  检测到并发配置编辑时停止替换。
- 回执位于 `$CODEX_HOME/provider-fork/receipts/`。结果不确定时不自动重试；
  已成功的旧持久回执不会覆盖后来有意修改的默认值。
- 新分支使用 `workspace-write`、`on-request` 审批、禁用 memories 和默认
  service tier。工具不会自动批准交互式服务器请求。这些权限不能强隔离
  不受信任的模型与本地凭据文件。
- 继续推理时，fork 的历史会发送到选中的 Provider。切换前应检查敏感历史。
  保留登录不代表对任何服务的账号风控决定作出保证。

正常路径是原生 fork。只有实际失败后才读取
[故障恢复参考](skills/provider-fork/references/failure-recovery.md)，摘要 handoff
是异常情况下的后备处理。

## 仓库结构

```text
codex-app-provider-fork/
├── README.md
├── README.zh-CN.md
├── LICENSE
├── requirements.txt
├── tests/
└── skills/
    └── provider-fork/
        ├── SKILL.md
        ├── agents/openai.yaml
        ├── references/failure-recovery.md
        └── scripts/provider_fork.py
```

根目录 README 是仓库文档；仅将 `skills/provider-fork/` 安装到 Codex 的
skills 目录。Skill 及其 reference 全部使用英文，不包含特定机器的连接说明。

## 验证

```bash
python -m unittest discover -s tests -v
python /path/to/skill-creator/scripts/quick_validate.py skills/provider-fork
```

默认测试覆盖名称前缀、fork 失败行为、Provider 检查和最小化持久配置修改，
不访问真实 App 状态。原生集成测试需要显式开启，使用临时 `CODEX_HOME`、
假凭据和本地模拟 Responses 服务。它们使用真实 Codex 可执行文件，不向
官方或第三方服务发起推理请求：

```bash
PROVIDER_FORK_NATIVE_TESTS=1 python -m unittest discover -s tests -v
```

PowerShell 中先设置 `$env:PROVIDER_FORK_NATIVE_TESTS = '1'`，再运行相同的
unittest 命令。原生测试覆盖 fork 后继续推理、专属 Authorization 请求头、
配置/认证保持不变、重启恢复、恢复覆盖和持久回执恢复。

## 兼容性

实验性工具。已验证 Linux 上的 Codex CLI `0.161.0`，以及 Windows App
自带的 CLI `0.162.0-alpha.2`（App `26.1002.7124.0`）。BeeAPI、Krill Code
和官方路线的短会话实际 fork 测试也成功。该结果不证明所有模型、长压缩历史、
后续 App 版本或 macOS 环境均兼容；测试中没有实际 Provider 拒绝证明必须 handoff。

Codex 升级后应重新运行隔离测试。普通内置会话工具仍然有用；本工具提供该
切换流程需要的显式 Provider 覆盖和可选的持久默认值修改。
