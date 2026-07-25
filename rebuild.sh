#!/usr/bin/env bash
# 删除并重建 SQLite 数据库（种子来自 content/ + levels/ + data/，全部在 git 内）
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
rm -f stock_learning.db
"$PY" -m app.seed
