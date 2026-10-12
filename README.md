# wechat-clawbot-notify

> 一个 `clawbot` 命令，把任意文本 / 图片推到你自己的微信。AI 跑完长活顺手发条通知，人不用盯终端。
> One-way WeChat notifications from your own terminal or agent: `clawbot send "build done"`.

给 Agent（Claude Code / Codex / pi / Cursor 等）用的 [SKILL.md](./SKILL.md)，也是给人用的 CLI。
底层是第三方 PyPI 包 [`wechat-clawbot-sdk`](https://pypi.org/project/wechat-clawbot-sdk/)，直连微信 ClawBot 网关，只需要「发消息」，**不需要常驻 agent、不需要企业微信、不需要公网服务器**。

## 为什么是这个而不是官方 ClawBot plugin

官方的 OpenClaw / ClawBot plugin 做的是**双向聊天**（微信 ↔ 你的 agent，bot 要常驻接消息、回消息）。
如果你只是想要一条**能发图、内容随意、把消息发到自己微信**的通知通道 —— 也就是 cron / CI / AI 任务结束时的「叮」—— 那不需要那一整套，`clawbot send` 一行就够，且几 MB 依赖、无守护进程要求。

## 30 秒开始

```bash
git clone https://github.com/nephen/wechat-clawbot-notify ~/.claude/skills/wechat-clawbot-notify
bash ~/.claude/skills/wechat-clawbot-notify/install.sh
```

`install.sh` 会建一个独立 venv（Python ≥3.11，优先用 uv，不动你的系统 Python）、装依赖、把 `clawbot` 放到 `~/.local/bin`。可以重复执行。

Codex 请把目录换成 `~/.codex/skills/`，pi 用 `~/.pi/agent/skills/`。Windows 在 WSL 或 Git Bash 里跑。

### 让 AI 替你装

把下面这段原话发给有 shell 权限的 Agent 就行：

```text
帮我安装 wechat-clawbot-notify。请把
https://github.com/nephen/wechat-clawbot-notify 克隆到
~/.claude/skills/wechat-clawbot-notify，然后执行其中的 install.sh，
装完跑一次 clawbot status 确认命令可用，并告诉我下一步需要我在微信里做什么。
```

已经装过的，用这段更新：

```text
帮我更新 wechat-clawbot-notify：进入 ~/.claude/skills/wechat-clawbot-notify 执行 git pull，
然后重跑 install.sh，最后告诉我最新 commit。
```

## 首次登录（这两步必须真人操作）

```bash
clawbot login          # 终端画 ASCII 二维码 → 微信「扫一扫」授权，凭据落盘，以后不用重扫
```

然后**在微信里主动给这个 ClawBot 发一条消息**（任意内容，比如 `hi`），再跑：

```bash
clawbot pair 60        # 监听 60 秒，把你的 user_id + context_token 落盘
```

这两步之后就能推送了。为什么必须有第 2 步见 [硬约束](#硬约束不是脚本的-bug)。

## 用法

```bash
clawbot send "部署完成，healthcheck 200"          # 文本通知
clawbot send < /tmp/report.md                     # 多行内容走 stdin（heredoc 也行）
clawbot image /tmp/screenshot.png "登录页截图"     # 图片：本地路径或 http(s) URL，可跟一段说明
clawbot status                                    # 账号 / 可推送目标 / token 状态
clawbot listen 0                                  # 常驻保活：自动接住入站消息并续 context_token
clawbot pair 60                                   # 一次性拿 context_token（有 listen 就不必）
```

接进 AI 工作流 —— 对 Agent 说一句「跑完发微信通知我」，它执行：

```bash
npm run build 2>&1 | tail -20; clawbot send "build 完成: $(git rev-parse --short HEAD)"
```

定时任务：

```cron
0 7 * * *  CLAWBOT_STATE_DIR=$HOME/.clawbot-notify/state $HOME/.local/bin/clawbot send "早，该盯盘了"
```

### 常驻保活（推荐）

`clawbot listen 0` 会随时接住你在微信里发的消息并把新的 `context_token` 落盘，有了它基本不会再遇到 token 过期。systemd 单位示例（也写在 [SKILL.md](./SKILL.md) 里）：

```ini
# ~/.config/systemd/user/clawbot-listen.service
[Unit]
Description=ClawBot WeChat notify keepalive

[Service]
Type=simple
ExecStart=%h/.local/bin/clawbot listen 0
Restart=always
RestartSec=10
UMask=0077

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload && systemctl --user enable --now clawbot-listen
journalctl --user -u clawbot-listen -f     # 看到 [收到] 就是接住了你微信发的消息
```

不想上 systemd：`nohup clawbot listen 0 >>~/.clawbot-notify/listen.log 2>&1 &`。

## 硬约束（不是脚本的 bug）

微信 ClawBot **不能主动开启会话**。发送接口需要一个 `context_token`，它只在**人先给 bot 发过消息**时才产生并落盘：

- 刚 `login` 完就 `send` → 报「没有 context_token」，正常，去微信里发一条消息再 `pair`。
- token 过期 → `errcode -14` / `SessionExpiredError`，在微信里再发一条消息，等 listen 打印 `[收到]` 后重试 `clawbot send` 就行。
- **轮询本身不会续期 token**，常驻 listen 的价值是随时接住你发的那条消息（省掉手动 pair）+ 保持会话活跃。
- listen 跑着的时候**不要再另开 `pair`**：两个 poller 共用同一个 `get_updates_buf`，会互相抢消息。

## 文件位置

| | |
| --- | --- |
| CLI 脚本 | `scripts/clawbot.py`（本仓库内，只有一份） |
| 命令入口 | `~/.local/bin/clawbot`（install.sh 生成的小 wrapper） |
| venv | `~/.clawbot-notify/.venv` |
| 登录态 / 凭据 | `~/.clawbot-notify/state/accounts/*.json`（`umask 077`，只有你自己可读） |

数据目录与 skill 目录分离，`git pull` 更新代码不会碰到凭据。可用 `CLAWBOT_HOME` / `CLAWBOT_BIN_DIR` / `CLAWBOT_STATE_DIR` 覆盖。

## 风险与限制

- 非腾讯官方开放接口，走的是微信 ClawBot 内部网关，**随时可能因对方变动而失效**；失效时先 `uv pip install --python ~/.clawbot-notify/.venv/bin/python -U wechat-clawbot-sdk`。
- 凭据即你的 bot 会话，`bot_token` 不要提交、不要贴进日志/issue。
- 单向推送，不要拿来做群发/营销：这不是它的设计目标，也不安全。
- 代码按 MIT 发布，出问题自己兜着（no warranty）。

## 反馈

Issue 里请带上：`clawbot status` 的输出（把 `bot_token` 那行删掉）、报错原文、Python 版本、OS。

## License

MIT — 见 [LICENSE](./LICENSE)。
