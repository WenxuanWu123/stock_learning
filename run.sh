#!/usr/bin/env bash
# 一条命令起站：建 venv -> 装依赖 -> (缺库则)重建 -> 起服务。幂等，可重复执行。
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "[run] 创建 .venv"
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import fastapi, uvicorn, markdown, pandas, pyarrow" 2>/dev/null; then
  echo "[run] 安装依赖"
  .venv/bin/pip install -q -r requirements.txt
fi
if [ ! -f stock_learning.db ]; then
  echo "[run] 首次运行，重建数据库"
  ./rebuild.sh
fi
if [ ! -f stocks.db ] && [ -d data/stocks/daily ]; then
  echo "[run] 首次运行，构建个股库（约 1 分钟）"
  .venv/bin/python scripts/build_stocks_db.py
fi
echo "[run] 启动: http://127.0.0.1:8000"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
