# -*- coding: utf-8 -*-
"""种子管线：从 data/ 冻结 CSV + content/ + levels/ 一键重建数据库。

用法: .venv/bin/python -m app.seed   （由 rebuild.sh 调用）
"""
import csv
import json
import re
import sys
from pathlib import Path

import markdown

from . import calc, market
from .db import connect, init_db, DB_PATH, BASE_DIR

DATA_DIR = BASE_DIR / "data"
CONTENT_DIR = BASE_DIR / "content"
LEVELS_DIR = BASE_DIR / "levels"

# 四大模块，开工顺序固定（项目.md）
MODULES = [
    ("concepts", "股市概念"),
    ("indicators", "技术指标"),
    ("macro", "宏观经济学基础"),
    ("trading", "看盘技巧"),
]

# data/ 文件名 -> symbol
SYMBOL_FILES = {
    "sh000001.csv": "sh000001",
    "sh000300.csv": "sh000300",
    "sh000905.csv": "sh000905",
}

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_front_matter(text):
    """解析简易 YAML front-matter：支持 title/order 标量与 sources 列表。"""
    m = FM_RE.match(text)
    if not m:
        raise ValueError("lesson.md 缺少 front-matter（--- 包裹的 title/order/sources）")
    meta, sources, cur_key = {}, [], None
    for line in m.group(1).splitlines():
        if re.match(r"^\s+-\s+", line) and cur_key:
            meta[cur_key].append(re.sub(r"^\s+-\s+", "", line).strip())
        elif ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v == "":
                meta[k] = []
                cur_key = k
            else:
                meta[k] = v.strip('"').strip("'")
                cur_key = None
    for key in ("title", "order", "sources"):
        if key not in meta:
            raise ValueError(f"front-matter 缺少必填字段: {key}")
    meta["order"] = int(meta["order"])
    return meta, text[m.end():]


def import_market_data(conn):
    for fname, symbol in SYMBOL_FILES.items():
        path = DATA_DIR / fname
        if not path.exists():
            print(f"  警告: 缺少 {fname}，跳过 {symbol}")
            continue
        with open(path, newline="", encoding="utf-8") as f:
            rows = [(symbol, r["date"], r["open"], r["high"], r["low"],
                     r["close"], r["volume"]) for r in csv.DictReader(f)]
        conn.executemany(
            "INSERT OR REPLACE INTO market_data VALUES (?,?,?,?,?,?,?)", rows)
        print(f"  行情 {symbol}: {len(rows)} 行 <- {fname}")
    conn.commit()


def seed_content(conn):
    for ord_, (slug, title) in enumerate(MODULES, 1):
        conn.execute("INSERT INTO modules (slug, title, ord) VALUES (?,?,?)",
                     (slug, title, ord_))
        mod_dir = CONTENT_DIR / slug
        if not mod_dir.is_dir():
            continue
        module_id = conn.execute("SELECT id FROM modules WHERE slug=?", (slug,)).fetchone()["id"]
        for chap_dir in sorted(p for p in mod_dir.iterdir() if p.is_dir()):
            lesson_path = chap_dir / "lesson.md"
            quiz_path = chap_dir / "quiz.json"
            if not lesson_path.exists():
                print(f"  警告: {chap_dir} 缺少 lesson.md，跳过")
                continue
            meta, body = parse_front_matter(lesson_path.read_text(encoding="utf-8"))
            body_html, log1 = calc.inject(conn, body)
            html = markdown.markdown(body_html, extensions=["tables", "fenced_code"])
            cur = conn.execute(
                "INSERT INTO chapters (module_id, slug, title, ord) VALUES (?,?,?,?)",
                (module_id, chap_dir.name, meta["title"], meta["order"]))
            chapter_id = cur.lastrowid
            conn.execute(
                "INSERT INTO lessons (chapter_id, rendered_html, sources_json, calc_log)"
                " VALUES (?,?,?,?)",
                (chapter_id, html, json.dumps(meta["sources"], ensure_ascii=False),
                 "\n".join(log1)))
            n_q = 0
            if quiz_path.exists():
                quiz = json.loads(quiz_path.read_text(encoding="utf-8"))
                for idx, q in enumerate(quiz["questions"]):
                    q_text, lq = calc.inject(conn, q["q"])
                    opts, expl = [], q["explanation"]
                    for o in q["options"]:
                        o2, lo = calc.inject(conn, o)
                        opts.append(o2); lq += lo
                    expl, le = calc.inject(conn, expl)
                    if lq or le:
                        conn.execute(
                            "UPDATE lessons SET calc_log = calc_log || ? WHERE chapter_id=?",
                            ("\n" + "\n".join(lq + le), chapter_id))
                    conn.execute(
                        "INSERT INTO questions (chapter_id, idx, q, options_json, answer,"
                        " explanation) VALUES (?,?,?,?,?,?)",
                        (chapter_id, idx, q_text, json.dumps(opts, ensure_ascii=False),
                         int(q["answer"]), expl))
                    n_q += 1
            print(f"  章节 {slug}/{chap_dir.name}: {meta['title']}（{n_q} 题，"
                  f"注入 {len(log1)} 处课文数字）")
    conn.commit()


def seed_levels(conn):
    if not LEVELS_DIR.is_dir():
        return
    for path in sorted(LEVELS_DIR.glob("*.json")):
        lv = json.loads(path.read_text(encoding="utf-8"))
        question, log = calc.inject(conn, lv["question"])
        options = []
        for o in lv["options"]:
            text, l1 = calc.inject(conn, o["text"])
            fb, l2 = calc.inject(conn, o["feedback"])
            options.append({"key": o["key"], "text": text,
                            "score": int(o["score"]), "feedback": fb})
            log += l1 + l2
        conn.execute(
            "INSERT INTO levels (slug, title, symbol, decision_date, reveal_days,"
            " context_days, question, options_json, calc_log)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (path.stem, lv["title"], lv["symbol"], lv["decision_date"],
             int(lv["reveal_days"]), int(lv.get("context_days", 120)),
             question, json.dumps(options, ensure_ascii=False), "\n".join(log)))
        print(f"  关卡 {path.name}: {lv['title']}（决策日 {lv['decision_date']}）")
    conn.commit()


def main():
    if DB_PATH.exists():
        print(f"错误: {DB_PATH} 已存在。请先运行 ./rebuild.sh（它会先删库）。", file=sys.stderr)
        sys.exit(1)
    conn = connect()
    init_db(conn)
    print("[1/3] 导入行情")
    import_market_data(conn)
    print("[2/3] 注入课文与题目")
    seed_content(conn)
    print("[3/3] 注入关卡")
    seed_levels(conn)
    conn.close()
    market.clear_cache()
    print(f"完成 -> {DB_PATH}")


if __name__ == "__main__":
    main()
