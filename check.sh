#!/usr/bin/env bash
# 内容自检：校验格式 + 在临时库副本上试算全部 calc 占位符，不动 stock_learning.db。
# 用法: ./check.sh [文件或目录...]   （不带参数 = 全量检查 content/ + levels/）
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" scripts/check_content.py "$@"
