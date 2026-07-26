# -*- coding: utf-8 -*-
"""内容自检：供并行内容代理在 rebuild 前本地验证自己写的文件，不碰 stock_learning.db。

校验范围（默认全量，也可传入指定文件/目录）：
  content/<module>/<NN>-<slug>/lesson.md   front-matter 必填字段
  content/<module>/<NN>-<slug>/quiz.json   JSON 语法 + 字段格式 + 题数 + answer 范围
  levels/*.json                            JSON 语法 + 关卡必填字段
  以上文件中所有 {{calc:...}} 占位符在**临时数据库副本**上实际求值

退出码：全部通过 0，否则 1 并打印问题清单（文件:行号:原因）。
并发安全：临时库用 tempfile 唯一名，多进程同时跑互不干扰。
"""
import argparse
import datetime
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import calc  # noqa: E402
from app.db import connect, init_db, DB_PATH  # noqa: E402
from app.market import SYMBOL_NAMES, get_series  # noqa: E402
from app.seed import parse_front_matter, import_market_data  # noqa: E402

CALC_RE = re.compile(r"\{\{calc:([^}|]+)(?:\|(\d+))?\}\}")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

problems = []  # (file, line, msg)


def err(path, line, msg):
    problems.append((str(path), line, msg))


# ── 收集待检文件 ──

def collect(paths):
    lessons, quizzes, levels = [], [], []
    if not paths:
        paths = [BASE_DIR / "content", BASE_DIR / "levels"]
    for p in paths:
        p = Path(p).resolve()
        if p.is_dir():
            lessons += sorted(p.rglob("lesson.md"))
            quizzes += sorted(p.rglob("quiz.json"))
            levels += sorted(f for f in p.rglob("*.json") if f.name != "quiz.json")
        elif p.name == "lesson.md":
            lessons.append(p)
        elif p.name == "quiz.json":
            quizzes.append(p)
        elif p.suffix == ".json":
            levels.append(p)
        else:
            err(p, 0, "无法识别的文件类型（应为 lesson.md / quiz.json / levels 下 .json）")
    # 去重
    return sorted(set(lessons)), sorted(set(quizzes)), sorted(set(levels))


# ── 格式校验 ──

def check_lesson(path):
    text = path.read_text(encoding="utf-8")
    try:
        meta, _ = parse_front_matter(text)
        if not isinstance(meta["sources"], list) or not meta["sources"]:
            err(path, 1, "front-matter 的 sources 至少一条")
    except ValueError as e:
        err(path, 1, f"front-matter 错误: {e}")
    return text


def check_quiz(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(path, e.lineno, f"JSON 语法错误: {e.msg}")
        return ""
    qs = data.get("questions")
    if not isinstance(qs, list) or not qs:
        err(path, 1, "顶层必须是 {\"questions\": [...]} 且非空")
        return path.read_text(encoding="utf-8")
    if len(qs) != 10:
        err(path, 1, f"题数应为 10（项目.md 规定每章 10 题），实际 {len(qs)}")
    for i, q in enumerate(qs):
        tag = f"第{i + 1}题"
        if not isinstance(q.get("q"), str) or not q["q"].strip():
            err(path, 0, f"{tag}: q 缺失或为空")
        opts = q.get("options")
        if not isinstance(opts, list) or len(opts) != 4 or not all(isinstance(o, str) for o in opts):
            err(path, 0, f"{tag}: options 必须是 4 个字符串")
            continue
        ans = q.get("answer")
        if not isinstance(ans, int) or not (0 <= ans < len(opts)):
            err(path, 0, f"{tag}: answer 必须是 0~{len(opts) - 1} 的整数，实际 {ans!r}")
        if not isinstance(q.get("explanation"), str) or not q["explanation"].strip():
            err(path, 0, f"{tag}: explanation 缺失或为空（答错解析必填）")
    return path.read_text(encoding="utf-8")


def check_level(path):
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        err(path, e.lineno, f"JSON 语法错误: {e.msg}")
        return ""
    for key in ("title", "symbol", "decision_date", "reveal_days", "question", "options"):
        if key not in data:
            err(path, 1, f"缺少必填字段: {key}")
    sym = data.get("symbol")
    if sym is not None and sym not in SYMBOL_NAMES:
        err(path, 1, f"symbol 必须是 {'/'.join(SYMBOL_NAMES)} 之一，实际 {sym!r}")
    dd = data.get("decision_date")
    if dd is not None and not DATE_RE.match(str(dd)):
        err(path, 1, f"decision_date 应为 YYYY-MM-DD，实际 {dd!r}")
    elif dd is not None:
        try:
            datetime.date.fromisoformat(str(dd))
        except ValueError:
            err(path, 1, f"decision_date 不是合法日期: {dd!r}")
    for key in ("reveal_days", "context_days"):
        if key in data and (not isinstance(data[key], int) or data[key] <= 0):
            err(path, 1, f"{key} 必须是正整数，实际 {data[key]!r}")
    opts = data.get("options")
    if isinstance(opts, list):
        if len(opts) < 2:
            err(path, 1, "options 至少 2 个")
        keys = set()
        for i, o in enumerate(opts):
            tag = f"选项{i + 1}"
            if not isinstance(o, dict):
                err(path, 1, f"{tag}: 必须是对象")
                continue
            for key in ("key", "text", "score", "feedback"):
                if key not in o:
                    err(path, 1, f"{tag}: 缺少字段 {key}")
            if "key" in o:
                if o["key"] in keys:
                    err(path, 1, f"选项 key 重复: {o['key']!r}")
                keys.add(o["key"])
            if "score" in o and (not isinstance(o["score"], int) or not (0 <= o["score"] <= 100)):
                err(path, 1, f"{tag}: score 必须是 0~100 整数，实际 {o['score']!r}")
    elif "options" in data:
        err(path, 1, "options 必须是数组")
    return text


# ── calc 占位符求值（临时库副本） ──

def make_temp_db():
    """复制现有库（sqlite backup，对运行中的服务安全）；库不存在则建临时库只导行情。"""
    fd, tmp = tempfile.mkstemp(prefix="check_content_", suffix=".db")
    Path(tmp).unlink(missing_ok=True)  # 让 sqlite 自己创建
    import os
    os.close(fd)
    if DB_PATH.exists():
        src = sqlite3.connect(str(DB_PATH))
        dst = sqlite3.connect(tmp)
        src.backup(dst)
        dst.close()
        src.close()
    else:
        conn = connect(tmp)
        init_db(conn)
        import_market_data(conn)
        conn.close()
    return tmp


def calc_positions(path, text):
    """返回 [(line_no, expr, digits)]，expr 不含 {{calc:、}} 与 |精度。"""
    out = []
    for ln, line in enumerate(text.splitlines(), 1):
        for m in CALC_RE.finditer(line):
            out.append((ln, m.group(1), int(m.group(2)) if m.group(2) else 2))
    return out


def check_calc(conn, path, text, level_symbol=None, decision_date=None):
    for ln, expr, digits in calc_positions(path, text):
        try:
            calc.eval_placeholder(conn, expr, digits)
        except Exception as e:
            err(path, ln, f"calc 求值失败: {e}")
    # 关卡附加：决策日在行情表内有数据
    if level_symbol and decision_date and DATE_RE.match(str(decision_date)):
        try:
            s = get_series(conn, level_symbol)
            s.idx_on_or_before(str(decision_date))
        except Exception as e:
            err(path, 1, f"decision_date 无行情数据: {e}")


def main():
    ap = argparse.ArgumentParser(description="内容自检（不动 stock_learning.db）")
    ap.add_argument("paths", nargs="*", help="要检查的文件/目录，默认 content/ + levels/ 全量")
    args = ap.parse_args()

    lessons, quizzes, levels = collect([Path(p) for p in args.paths])
    if not (lessons or quizzes or levels):
        print("没有找到任何待检文件。")
        return 1

    tmp_db = make_temp_db()
    try:
        conn = connect(tmp_db)
        n = 0
        for p in lessons:
            text = check_lesson(p)
            check_calc(conn, p, text)
            n += 1
        for p in quizzes:
            text = check_quiz(p)
            if text:
                check_calc(conn, p, text)
            n += 1
        for p in levels:
            text = check_level(p)
            if text:
                try:
                    d = json.loads(text)
                    sym, dd = d.get("symbol"), d.get("decision_date")
                except json.JSONDecodeError:
                    sym = dd = None
                check_calc(conn, p, text, sym, dd)
            n += 1
        conn.close()
    finally:
        Path(tmp_db).unlink(missing_ok=True)

    checked = f"{len(lessons)} 课文 / {len(quizzes)} 题库 / {len(levels)} 关卡"
    if problems:
        print(f"✗ 自检未通过（{checked}，共 {len(problems)} 个问题）：")
        for f, ln, msg in problems:
            loc = f"{f}:{ln}" if ln else f
            print(f"  - {loc}: {msg}")
        return 1
    print(f"✓ 自检通过（{checked}，临时库 calc 求值全部成功，未动 stock_learning.db）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
