#!/usr/bin/env bash
# 一键启动教学站并打开浏览器。可反复执行（幂等）。
cd "$(dirname "$0")"
URL="http://127.0.0.1:8000"

# 服务没在跑就拉起来
if ! curl -sf "$URL/api/modules" >/dev/null 2>&1; then
  if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
  fi
  [ -f stock_learning.db ] || ./rebuild.sh
  nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
  for i in $(seq 1 30); do
    curl -sf "$URL/api/modules" >/dev/null 2>&1 && break
    sleep 1
  done
fi

# 打开浏览器（WSL 优先用 Windows 浏览器）
if command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe /c start "$URL" >/dev/null 2>&1
elif command -v wslview >/dev/null 2>&1; then
  wslview "$URL"
else
  xdg-open "$URL" >/dev/null 2>&1 &
fi
echo "教学站已就绪: $URL"
