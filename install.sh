#!/usr/bin/env bash
# 一键安装 wechat-clawbot-notify：建 venv（Python ≥3.11）+ 装依赖 + 生成 `clawbot` 命令。
# 可重复执行（幂等）。要卸载就删掉 DATA_DIR 和 BIN_DIR/clawbot。
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${CLAWBOT_HOME:-$HOME/.clawbot-notify}"
VENV="$DATA_DIR/.venv"
BIN_DIR="${CLAWBOT_BIN_DIR:-$HOME/.local/bin}"
PY_FLOOR=(3.13 3.12 3.11)

mkdir -p "$DATA_DIR/state" "$BIN_DIR"

venv_py="$VENV/bin/python"
if [ ! -x "$venv_py" ]; then
  if command -v uv >/dev/null 2>&1; then
    echo "== uv 创建 venv（自动拉 Python 3.11）"
    uv venv --python 3.11 "$VENV"
  else
    py=""
    for c in "${PY_FLOOR[@]}"; do
      if command -v "python$c" >/dev/null 2>&1; then py="python$c"; break; fi
    done
    [ -z "$py" ] && command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' && py=python3
    [ -z "$py" ] && { echo "找不到 Python ≥3.11（SDK 硬要求）。先装一个，或装 uv：curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
    echo "== $py -m venv 创建 venv"
    "$py" -m venv "$VENV"
  fi
fi

echo "== 安装依赖 wechat-clawbot-sdk + qrcode"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$venv_py" wechat-clawbot-sdk qrcode
else
  "$venv_py" -m pip install --upgrade pip >/dev/null
  "$venv_py" -m pip install wechat-clawbot-sdk qrcode
fi

echo "== 生成 $BIN_DIR/clawbot"
cat > "$BIN_DIR/clawbot" <<EOF
#!/bin/sh
# 登录态跟着 CLAWBOT_HOME 走；单独想换位置就设 CLAWBOT_STATE_DIR
export CLAWBOT_STATE_DIR="\${CLAWBOT_STATE_DIR:-$DATA_DIR/state}"
exec "$venv_py" "$SKILL_DIR/scripts/clawbot.py" "\$@"
EOF
chmod +x "$BIN_DIR/clawbot"

if ! command -v clawbot >/dev/null 2>&1; then
  echo "!! $BIN_DIR 不在 PATH 里，先加一句到你的 shell rc："
  echo "   export PATH=\"$BIN_DIR:\$PATH\""
fi

echo "== 验证"
"$BIN_DIR/clawbot" status || true
cat <<EOF

安装完成。接下来两步（都需要你本人在微信里操作一次）：
  1) clawbot login                # 终端出二维码，微信「扫一扫」授权
  2) 在微信里主动给 ClawBot 发一条消息，然后 clawbot pair 60
之后就能： clawbot send "部署完成了" / clawbot image /tmp/a.png "截图"
EOF
