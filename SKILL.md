---
name: wechat-clawbot-notify
description: >-
  Push notifications to the user's own WeChat via a WeChat ClawBot — text or images, arbitrary content:
  "notify me on WeChat when the build/deploy/long job finishes", "发微信通知", "clawbot send", "把结果推到微信",
  "AI 做完后发条微信给我". Also fixes ClawBot push failures: errcode -14 / SessionExpiredError,
  "没有 context_token", bot cannot open the conversation, login QR won't scan.
  One-way notify only — for a two-way WeChat chat agent use the official OpenClaw ClawBot plugin instead.
---

# WeChat ClawBot 单向通知

一个 `clawbot` 命令：把任意文本 / 图片推到**你自己的微信**（微信 ClawBot 会话）。
典型用法是 AI 干完一个长活（构建、部署、爬取、跑测试）之后，顺手 `clawbot send "完成了，3 个失败"`，人不用盯着终端。

底层是第三方 PyPI SDK [`wechat-clawbot-sdk`](https://pypi.org/project/wechat-clawbot-sdk/)（非腾讯官方开放接口），只用它的发消息能力，不需要常驻 agent。

## When to Use

- 用户要「做完发微信通知我」「把结果/报错/截图推到微信」。
- 定时任务、CI、后台脚本需要一个人到手的通知通道。
- 排错：`clawbot send` 报 `-14` / `context_token` 缺失 / 登录后发不出去。

不要用：需要双向对话的微信机器人（那要装官方 ClawBot plugin）。

## Install（AI 可直接执行）

前提：Linux/macOS（Windows 请在 WSL 或 Git Bash 里跑），有 `git`、`curl`，Python ≥ 3.11（脚本会自己建 venv，不动系统 Python）。

```bash
# 1. 克隆到 agent 的 skills 目录（Claude Code 用 ~/.claude/skills，Codex 用 ~/.codex/skills，pi 用 ~/.pi/agent/skills）
git clone https://github.com/nephen/wechat-clawbot-notify ~/.claude/skills/wechat-clawbot-notify

# 2. 装依赖 + 生成 clawbot 命令（幂等，可重复跑）
bash ~/.claude/skills/wechat-clawbot-notify/install.sh
```

装完 `clawbot` 落在 `~/.local/bin/clawbot`，venv 与登录态在 `~/.clawbot-notify/`（跟 skill 目录分离，`git pull` 更新 skill 不会碰凭据）。

给 AI 的原话模板：

> 帮我安装 wechat-clawbot-notify：把 https://github.com/nephen/wechat-clawbot-notify 克隆到 `~/.claude/skills/wechat-clawbot-notify`，然后执行其中的 `install.sh`，跑完确认 `clawbot status` 有输出。

## First-time setup（这两步必须真人操作，AI 代劳不了）

1. `clawbot login` — 终端画 ASCII 二维码，用微信「扫一扫」授权。会话落盘，之后不用再扫。
2. **在微信里主动给 ClawBot 发一条消息**，然后 `clawbot pair 60`（或跑着常驻 listen 就不必 pair）。

第 2 步不是可选项，见下面硬约束。

## Usage

```bash
clawbot send "部署完成，healthcheck 200"        # 文本
clawbot send < /tmp/report.md                   # 多行/管道（heredoc 也行）
echo "test 3 failed: $(...)" | clawbot send
clawbot image /tmp/screenshot.png "登录页截图"   # 本地路径或 http(s) URL，后面可跟说明
clawbot status                                  # 账号 / 可推送目标 / token 状态
clawbot listen 0                                # 常驻保活：接住入站消息并自动续 context_token
```

`clawbot image` 之后仍可再 `clawbot send` 补文字；长文本会被微信截断，控制在几百字内更稳。

### 后台保活（推荐，省掉每次 pair）

`clawbot listen 0` 常驻会随时接住你在微信里发的消息，把新的 `context_token` 落盘，`send` 就不会过期失效。

systemd（Linux）：

```ini
# /etc/systemd/system/clawbot-listen.service
[Service]
Type=simple
ExecStart=%h/.local/bin/clawbot listen 0
Restart=always
RestartSec=10
UMask=0077
[Install]
WantedBy=multi-user.target
```

`systemctl --user daemon-reload && systemctl --user enable --now clawbot-listen`；临时用 `nohup clawbot listen 0 >>~/.clawbot-notify/listen.log 2>&1 &` 也可以。

## Pitfalls

- **ClawBot 不能主动开场**：`send_*` 需要一个 `context_token`，它只在**人先给 bot 发消息**时产生。刚 login 完直接 send 必然报「没有 context_token」。
- token 过期表现为 `errcode -14` / `SessionExpiredError`：在微信里再发一条消息，等 listen 打印 `[收到]`（或跑 `clawbot pair 60`）后重试即可。轮询本身**不续期** token。
- **别在 listen 运行时再跑 `pair`**：两个 poller 共用同一个 `get_updates_buf`，会互相抢消息，表现为谁都收不到。先停 listen 再 pair。
- 多账号：`~/.clawbot-notify/state/accounts/*.json` 每个登录一份，脚本取 mtime 最新且有 token 的那个。`account_id` 形如 `117e461e157a@im.bot` 自带点，只能按 `.sync.json` / `.context-tokens.json` 后缀排除附属文件，不能用文件名（stem）过滤。
- `bot_token` 是凭据，state 目录已 `umask 077`；**不要把 `~/.clawbot-notify/` 提交进 git**，也别打印 token 全文。
- Python < 3.11 会被 SDK 拒装；`install.sh` 会用 uv 或找 3.11/3.12/3.13，不会污染系统环境。
- 这是非官方接口，随时可能因微信侧变动失效；失效时优先 `pip install -U wechat-clawbot-sdk`。

## Verification

1. `clawbot status` 列出 `account_id=` 且有一行 `可推送目标: <user_id>`。
2. `clawbot send "skill 自检"` 打印 `已发送 -> <user_id>`，且微信里真收到。
3. `clawbot image <任意小图> "自检配图"` 打印 `图片已发送 -> <user_id>`，微信里能看到图。
