#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户数据（答题记录/错题本/关卡成绩）跨 rebuild 保留。

rebuild.sh 删库前 export 到 private/user_backup.json，seed 完成后 import 回来。
题目按「章节 slug + 题干文本」重新定位（rebuild 后自增 ID 可能漂移），
关卡按 slug 定位；找不到对应内容的历史记录丢弃并计数提示。
private/ 已 gitignore，备份不会进仓库。
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import db  # noqa: E402

BACKUP = BASE / "private" / "user_backup.json"


def export():
    if not db.DB_PATH.exists():
        print("无数据库，跳过导出")
        return
    conn = db.connect()
    answers = conn.execute(
        "SELECT c.slug chapter_slug, q.q qtext, a.chosen, a.correct, a.ts"
        " FROM answers a JOIN questions q ON q.id=a.question_id"
        " JOIN chapters c ON c.id=q.chapter_id").fetchall()
    wrong = conn.execute(
        "SELECT c.slug chapter_slug, q.q qtext, w.wrong_count, w.last_ts"
        " FROM wrongbook w JOIN questions q ON q.id=w.question_id"
        " JOIN chapters c ON c.id=q.chapter_id").fetchall()
    attempts = conn.execute(
        "SELECT l.slug level_slug, a.chosen, a.score, a.ts"
        " FROM level_attempts a JOIN levels l ON l.id=a.level_id").fetchall()
    conn.close()
    BACKUP.parent.mkdir(exist_ok=True)
    BACKUP.write_text(json.dumps({
        "answers": [dict(r) for r in answers],
        "wrongbook": [dict(r) for r in wrong],
        "level_attempts": [dict(r) for r in attempts],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已备份: {len(answers)} 答题 / {len(wrong)} 错题 / {len(attempts)} 关卡记录")


def import_():
    if not BACKUP.exists():
        print("无备份文件，跳过恢复")
        return
    data = json.loads(BACKUP.read_text(encoding="utf-8"))
    conn = db.connect()
    qid = {(r["slug"], r["q"]): r["id"] for r in conn.execute(
        "SELECT q.id, q.q, c.slug FROM questions q JOIN chapters c ON c.id=q.chapter_id")}
    lid = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM levels")}
    na = nw = nl = da = dw = dl = 0
    for a in data.get("answers", []):
        i = qid.get((a["chapter_slug"], a["qtext"]))
        if i:
            conn.execute("INSERT INTO answers (question_id, chosen, correct, ts) VALUES (?,?,?,?)",
                         (i, a["chosen"], a["correct"], a["ts"]))
            na += 1
        else:
            da += 1
    for w in data.get("wrongbook", []):
        i = qid.get((w["chapter_slug"], w["qtext"]))
        if i:
            conn.execute("INSERT INTO wrongbook (question_id, wrong_count, last_ts) VALUES (?,?,?)",
                         (i, w["wrong_count"], w["last_ts"]))
            nw += 1
        else:
            dw += 1
    for t in data.get("level_attempts", []):
        i = lid.get(t["level_slug"])
        if i:
            conn.execute("INSERT INTO level_attempts (level_id, chosen, score, ts) VALUES (?,?,?,?)",
                         (i, t["chosen"], t["score"], t["ts"]))
            nl += 1
        else:
            dl += 1
    conn.commit()
    conn.close()
    msg = f"已恢复: {na} 答题 / {nw} 错题 / {nl} 关卡记录"
    if da + dw + dl:
        msg += f"；因内容已变更丢弃: 答题{da} / 错题{dw} / 关卡{dl}"
    print(msg)


if __name__ == "__main__":
    {"export": export, "import": import_}[sys.argv[1]]()
