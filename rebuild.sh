#!/usr/bin/env bash
# 删除并重建 SQLite 数据库（种子来自 content/ + levels/ + data/，全部在 git 内）
# 用户数据（答题记录/错题本/关卡成绩）自动备份并在建库后恢复，不会因 rebuild 丢失。
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
[ -f stock_learning.db ] && "$PY" scripts/user_data.py export
rm -f stock_learning.db
"$PY" -m app.seed
"$PY" scripts/user_data.py import
