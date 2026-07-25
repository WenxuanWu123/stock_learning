# -*- coding: utf-8 -*-
"""FastAPI 后端：内容 API + 判分 + B 型关卡 + 成绩统计 + 静态前端。"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .db import connect, BASE_DIR
from .market import get_series, SYMBOL_NAMES
from . import v5

app = FastAPI(title="A股投资互动教学站")
STATIC_DIR = BASE_DIR / "static"


def db():
    return connect()


# ── 内容导航 ──

@app.get("/api/modules")
def list_modules():
    conn = db()
    mods = []
    for m in conn.execute("SELECT * FROM modules ORDER BY ord"):
        chaps = conn.execute(
            "SELECT id, slug, title, ord FROM chapters WHERE module_id=? ORDER BY ord",
            (m["id"],)).fetchall()
        mods.append({"id": m["id"], "slug": m["slug"], "title": m["title"],
                     "chapters": [dict(c) for c in chaps]})
    conn.close()
    return {"modules": mods}


@app.get("/api/chapters/{chapter_id}/lesson")
def get_lesson(chapter_id: int):
    conn = db()
    row = conn.execute(
        "SELECT c.title, l.rendered_html, l.sources_json FROM lessons l"
        " JOIN chapters c ON c.id=l.chapter_id WHERE l.chapter_id=?",
        (chapter_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "章节不存在")
    return {"title": row["title"], "html": row["rendered_html"],
            "sources": json.loads(row["sources_json"])}


@app.get("/api/chapters/{chapter_id}/quiz")
def get_quiz(chapter_id: int):
    conn = db()
    rows = conn.execute(
        "SELECT id, idx, q, options_json FROM questions WHERE chapter_id=? ORDER BY idx",
        (chapter_id,)).fetchall()
    conn.close()
    if not rows:
        raise HTTPException(404, "本章没有题目")
    return {"questions": [{"id": r["id"], "idx": r["idx"], "q": r["q"],
                           "options": json.loads(r["options_json"])} for r in rows]}


class AnswerIn(BaseModel):
    question_id: int
    chosen: int


@app.post("/api/answers")
def submit_answer(body: AnswerIn):
    conn = db()
    q = conn.execute("SELECT * FROM questions WHERE id=?", (body.question_id,)).fetchone()
    if not q:
        conn.close()
        raise HTTPException(404, "题目不存在")
    correct = int(body.chosen == q["answer"])
    conn.execute("INSERT INTO answers (question_id, chosen, correct) VALUES (?,?,?)",
                 (body.question_id, body.chosen, correct))
    if correct:
        conn.execute("DELETE FROM wrongbook WHERE question_id=?", (body.question_id,))
    else:
        conn.execute(
            "INSERT INTO wrongbook (question_id, wrong_count) VALUES (?,1)"
            " ON CONFLICT(question_id) DO UPDATE SET wrong_count=wrong_count+1,"
            " last_ts=datetime('now','localtime')", (body.question_id,))
    conn.commit()
    out = {"correct": bool(correct), "answer": q["answer"],
           "explanation": q["explanation"]}
    conn.close()
    return out


# ── B 型关卡 ──

def _candles(s, i0, i1):
    return [{"date": s.dates[i], "open": s.open[i], "high": s.high[i],
             "low": s.low[i], "close": s.close[i], "volume": s.volume[i]}
            for i in range(i0, i1 + 1)]


@app.get("/api/levels")
def list_levels():
    conn = db()
    rows = conn.execute("SELECT id, slug, title, symbol, decision_date FROM levels").fetchall()
    best = {r["level_id"]: r["best"] for r in conn.execute(
        "SELECT level_id, MAX(score) best FROM level_attempts GROUP BY level_id")}
    conn.close()
    return {"levels": [{**dict(r), "symbol_name": SYMBOL_NAMES.get(r["symbol"], r["symbol"]),
                        "best_score": best.get(r["id"])} for r in rows]}


@app.get("/api/levels/{level_id}")
def get_level(level_id: int):
    conn = db()
    lv = conn.execute("SELECT * FROM levels WHERE id=?", (level_id,)).fetchone()
    if not lv:
        conn.close()
        raise HTTPException(404, "关卡不存在")
    s = get_series(conn, lv["symbol"])
    di = s.idx_on_or_before(lv["decision_date"])
    i0 = max(0, di - lv["context_days"] + 1)
    options = json.loads(lv["options_json"])
    out = {
        "id": lv["id"], "title": lv["title"],
        "symbol": lv["symbol"], "symbol_name": SYMBOL_NAMES.get(lv["symbol"], lv["symbol"]),
        "decision_date": s.dates[di], "question": lv["question"],
        "options": [{"key": o["key"], "text": o["text"]} for o in options],
        "candles": _candles(s, i0, di),
    }
    conn.close()
    return out


class LevelIn(BaseModel):
    chosen: str


@app.post("/api/levels/{level_id}/submit")
def submit_level(level_id: int, body: LevelIn):
    conn = db()
    lv = conn.execute("SELECT * FROM levels WHERE id=?", (level_id,)).fetchone()
    if not lv:
        conn.close()
        raise HTTPException(404, "关卡不存在")
    options = json.loads(lv["options_json"])
    opt = next((o for o in options if o["key"] == body.chosen), None)
    if not opt:
        conn.close()
        raise HTTPException(400, "无效选项")
    s = get_series(conn, lv["symbol"])
    di = s.idx_on_or_before(lv["decision_date"])
    i1 = min(len(s.dates) - 1, di + lv["reveal_days"])
    future = _candles(s, di + 1, i1)
    # 决策日之后 reveal 期内的涨跌幅
    ret = None
    if future:
        ret = round((future[-1]["close"] / s.close[di] - 1) * 100, 2)
    status = v5.status_at(s, lv["decision_date"])
    conn.execute("INSERT INTO level_attempts (level_id, chosen, score) VALUES (?,?,?)",
                 (level_id, body.chosen, opt["score"]))
    conn.commit()
    conn.close()
    return {"score": opt["score"], "feedback": opt["feedback"],
            "future": future, "reveal_return_pct": ret, "v5": status}


# ── 成绩统计 / 错题本 ──

@app.get("/api/stats")
def stats():
    conn = db()
    total = conn.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"]
    ans = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(correct),0) c FROM answers").fetchone()
    per_chapter = conn.execute(
        "SELECT c.id, c.title, COUNT(a.id) attempts, COALESCE(SUM(a.correct),0) correct,"
        " (SELECT COUNT(*) FROM questions q WHERE q.chapter_id=c.id) total"
        " FROM chapters c LEFT JOIN questions q ON q.chapter_id=c.id"
        " LEFT JOIN answers a ON a.question_id=q.id"
        " GROUP BY c.id ORDER BY c.id").fetchall()
    levels = conn.execute(
        "SELECT l.id, l.title, COUNT(a.id) attempts, MAX(a.score) best"
        " FROM levels l LEFT JOIN level_attempts a ON a.level_id=l.id"
        " GROUP BY l.id").fetchall()
    wrong = conn.execute(
        "SELECT w.question_id, w.wrong_count, w.last_ts, q.q, c.title chapter_title"
        " FROM wrongbook w JOIN questions q ON q.id=w.question_id"
        " JOIN chapters c ON c.id=q.chapter_id ORDER BY w.last_ts DESC").fetchall()
    conn.close()
    return {
        "total_questions": total,
        "attempts": ans["n"], "correct": ans["c"],
        "accuracy": round(100 * ans["c"] / ans["n"], 1) if ans["n"] else None,
        "chapters": [dict(r) for r in per_chapter],
        "levels": [dict(r) for r in levels],
        "wrongbook": [dict(r) for r in wrong],
    }


@app.get("/api/wrongbook")
def wrongbook():
    conn = db()
    rows = conn.execute(
        "SELECT w.question_id, w.wrong_count, w.last_ts, q.q, q.options_json,"
        " q.answer, q.explanation, c.title chapter_title, c.id chapter_id"
        " FROM wrongbook w JOIN questions q ON q.id=w.question_id"
        " JOIN chapters c ON c.id=q.chapter_id ORDER BY w.last_ts DESC").fetchall()
    conn.close()
    return {"items": [{"question_id": r["question_id"], "wrong_count": r["wrong_count"],
                       "last_ts": r["last_ts"], "q": r["q"],
                       "options": json.loads(r["options_json"]), "answer": r["answer"],
                       "explanation": r["explanation"],
                       "chapter_title": r["chapter_title"],
                       "chapter_id": r["chapter_id"]} for r in rows]}


# ── 静态前端 ──

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
