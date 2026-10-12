#!/usr/bin/env python3
"""单向微信 ClawBot 通知 CLI（基于 wechat-clawbot-sdk）。

用法:
  clawbot login            扫码登录（首次一次即可，会话落盘复用）
  clawbot pair [秒数]      开监听并在微信里回一条消息，拿到 user_id + context_token（有常驻 listen 服务时不需要）
  clawbot send "内容"      推送文本到微信（多行用 stdin 管道: clawbot send < report.md）
  clawbot image <路径|URL> [说明文字]   推送图片到微信
  clawbot listen [秒数]    只监听不落回显（0 = 常驻，异常自动重连）——后台保活服务用这个
  clawbot status           看当前账号 / 可推送目标 / context 状态

状态目录: $CLAWBOT_STATE_DIR 或 ~/.clawbot-notify/state （SDK FileStateStore 格式，含 bot_token，勿提交 git）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import qrcode

# bot_token 是凭据，SDK 落盘的 state 文件不给其他用户读
os.umask(0o077)

STATE_DIR = Path(os.environ.get("CLAWBOT_STATE_DIR") or (Path.home() / ".clawbot-notify" / "state")).expanduser()

from wechat_clawbot_sdk import AsyncWeChatBotClient, PollEventType  # noqa: E402


def make_client() -> AsyncWeChatBotClient:
    return AsyncWeChatBotClient.create(state_dir=STATE_DIR)


SIDE_SUFFIXES = (".sync.json", ".context-tokens.json")


def account_ids() -> list[str]:
    """列出已登录账号（account_id 自身带点，如 xxx@im.bot，只能按后缀排附属文件）；最近登录的排前面。"""
    d = STATE_DIR / "accounts"
    if not d.is_dir():
        return []
    files = [p for p in d.glob("*.json") if not p.name.endswith(SIDE_SUFFIXES)]
    newest = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name[: -len(".json")] for p in newest]


def targets(account_id: str) -> dict[str, str]:
    """user_id -> context_token （由收到的入站消息落盘）"""
    f = STATE_DIR / "accounts" / f"{account_id}.context-tokens.json"
    if not f.is_file():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


def show_qr(content: str) -> None:
    """实测 qrcode_img_content 是 https 登录链接，终端里画 ASCII 二维码给微信扫码。"""
    if not content.startswith(("http://", "https://")):
        sys.exit(f"无法识别的二维码内容: {content[:160]}")
    code = qrcode.QRCode(border=1)
    code.add_data(content)
    code.make(fit=True)
    code.print_ascii(invert=True)
    print(f"请用微信「扫一扫」上方二维码（手机端也可打开: {content}）", flush=True)


def resolve_target() -> tuple[str, str]:
    """返回 (account_id, user_id)；多账号时取最近登录且有推送凭据的那个。"""
    for account_id in account_ids():
        t = targets(account_id)
        if t:
            return account_id, next(iter(t))
    if not account_ids():
        sys.exit("还没有登录，先跑 `clawbot login`")
    sys.exit("没有 context_token：先在微信里给 ClawBot 发一条消息（常驻 listen 在跑的话等几秒）")


async def cmd_login() -> None:
    client = make_client()
    try:
        qr = await client.start_login()
        show_qr(qr.qrcode_image_content)
        print("等待扫码确认…（二维码过期会自动刷新重画）", flush=True)
        session = await client.wait_for_login(qr.qrcode, on_qrcode_refresh=lambda fresh: show_qr(fresh.qrcode_image_content))
        print(f"登录成功 account_id={session.account_id} user_id={session.user_id}", flush=True)
        print("下一步：微信里给这个 ClawBot 发一条消息，然后跑 `clawbot pair 60` 拿到推送凭据", flush=True)
    finally:
        await client.close()


async def _listen(seconds: int, *, echo: bool = False) -> None:
    client = make_client()
    ids = account_ids()
    if not ids:
        sys.exit("还没有登录，先跑 `clawbot login`")
    account_id = ids[0]  # 只跟最近登录的账号，多个旧会话不重复轮询

    async def on_event(event):
        if event.event_type is not PollEventType.MESSAGE or event.message is None:
            return
        m = event.message
        print(f"[收到] account={account_id} user={m.user_id} text={(m.text or '')[:80]!r}", flush=True)
        if echo:
            await client.send_text(account_id=account_id, user_id=m.user_id, text=f"echo: {m.text or ''}")

    async def loop():
        while True:
            try:
                await client.consume_events(account_id, on_event, message_only=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # 网络抖动 / session 异常：10s 后重连，不让常驻进程死掉
                print(f"监听异常，10s 后重连: {exc}", file=sys.stderr, flush=True)
                await asyncio.sleep(10)

    try:
        print(f"监听中 account_id={account_id}{'（Ctrl-C 结束）' if seconds <= 0 else f' {seconds}s'}", flush=True)
        if seconds > 0:
            try:
                await asyncio.wait_for(loop(), seconds)
            except asyncio.TimeoutError:
                pass
        else:
            await loop()
        t = targets(account_id)
        print(f"当前可用推送目标: {list(t) or '无 —— 微信里没发过消息就发不出去'}", flush=True)
    finally:
        await client.close()


async def cmd_send(text: str) -> None:
    client = make_client()
    account_id, user_id = resolve_target()
    try:
        await client.send_text(account_id=account_id, user_id=user_id, text=text)
        print(f"已发送 -> {user_id}", flush=True)
    except Exception as exc:
        sys.exit(f"发送失败: {exc}（若是 -14 / context 过期，在微信里再发一条消息重试）")
    finally:
        await client.close()


async def cmd_send_image(path_or_url: str, text: str | None = None) -> None:
    client = make_client()
    account_id, user_id = resolve_target()
    is_url = path_or_url.startswith(("http://", "https://"))
    if not is_url and not Path(path_or_url).is_file():
        sys.exit(f"图片不存在: {path_or_url}")
    try:
        await client.send_image(
            account_id=account_id,
            user_id=user_id,
            local_path=None if is_url else path_or_url,
            remote_url=path_or_url if is_url else None,
            text=text,
        )
        print(f"图片已发送 -> {user_id}", flush=True)
    except Exception as exc:
        sys.exit(f"发送失败: {exc}（若是 -14 / context 过期，在微信里再发一条消息重试）")
    finally:
        await client.close()


async def cmd_status() -> None:
    ids = account_ids()
    if not ids:
        print(f"未登录（{STATE_DIR}/accounts 为空）")
        return
    for account_id in ids:
        f = STATE_DIR / "accounts" / f"{account_id}.json"
        s = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        print(f"account_id={account_id}")
        print(f"  bot_id={s.get('bot_id')}  本人 user_id={s.get('user_id')}")
        print(f"  base_url={s.get('base_url')}  bot_token={str(s.get('bot_token'))[:8]}…")
        for user_id in targets(account_id):
            print(f"  可推送目标: {user_id}")
        if not targets(account_id):
            print("  无可推送目标：需要先在微信里给 ClawBot 发一条消息（跑 `clawbot pair 60`）")


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    if cmd == "login":
        asyncio.run(cmd_login())
    elif cmd == "pair":
        asyncio.run(_listen(int(args[1]) if len(args) > 1 else 60, echo=True))
    elif cmd == "listen":
        asyncio.run(_listen(int(args[1]) if len(args) > 1 else 60))
    elif cmd == "send":
        text = " ".join(args[1:]).strip()
        if not text and not sys.stdin.isatty():  # 管道模式: echo xxx | clawbot send
            text = sys.stdin.read().strip()
        if not text:
            sys.exit("内容为空（用法: clawbot send \"文本\" 或 echo 文本 | clawbot send）")
        asyncio.run(cmd_send(text))
    elif cmd == "status":
        asyncio.run(cmd_status())
    elif cmd in ("image", "send-image"):
        if len(args) < 2:
            sys.exit('用法: clawbot image <本地路径或URL> [说明文字]')
        asyncio.run(cmd_send_image(args[1], " ".join(args[2:]) or None))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
