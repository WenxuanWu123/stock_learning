# -*- coding: utf-8 -*-
"""SQLite 数据库：schema 定义与连接助手。"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "stock_learning.db"

SCHEMA = """
-- 行情表：从 data/ 冻结 CSV 导入
CREATE TABLE market_data (
    symbol TEXT NOT NULL,
    date   TEXT NOT NULL,           -- YYYY-MM-DD
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, date)
);

-- 内容模块（concepts/indicators/macro/trading）
CREATE TABLE modules (
    id    INTEGER PRIMARY KEY,
    slug  TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    ord   INTEGER NOT NULL
);

-- 章节
CREATE TABLE chapters (
    id        INTEGER PRIMARY KEY,
    module_id INTEGER NOT NULL REFERENCES modules(id),
    slug      TEXT UNIQUE NOT NULL,       -- 目录名，如 01-what-is-stock
    title     TEXT NOT NULL,
    ord       INTEGER NOT NULL
);

-- 课文渲染缓存：seed 时完成 calc 注入 + Markdown 渲染
CREATE TABLE lessons (
    chapter_id    INTEGER PRIMARY KEY REFERENCES chapters(id),
    rendered_html TEXT NOT NULL,          -- 数字已注入的 HTML
    sources_json  TEXT NOT NULL DEFAULT '[]',
    calc_log      TEXT NOT NULL DEFAULT '' -- 每个占位符的替换记录，便于审计
);

-- 题目（每章 10 题）
CREATE TABLE questions (
    id          INTEGER PRIMARY KEY,
    chapter_id  INTEGER NOT NULL REFERENCES chapters(id),
    idx         INTEGER NOT NULL,
    q           TEXT NOT NULL,            -- 数字已注入
    options_json TEXT NOT NULL,           -- ["..","..","..",".."]
    answer      INTEGER NOT NULL,         -- 0-3
    explanation TEXT NOT NULL             -- 数字已注入
);

-- B 型关卡
CREATE TABLE levels (
    id            INTEGER PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    decision_date TEXT NOT NULL,
    reveal_days   INTEGER NOT NULL,
    context_days  INTEGER NOT NULL DEFAULT 120,
    question      TEXT NOT NULL,          -- 数字已注入
    options_json  TEXT NOT NULL,          -- [{"key","text","score","feedback"}] 数字已注入
    calc_log      TEXT NOT NULL DEFAULT ''
);

-- 答题记录
CREATE TABLE answers (
    id          INTEGER PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    chosen      INTEGER NOT NULL,
    correct     INTEGER NOT NULL,         -- 0/1
    ts          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 关卡成绩
CREATE TABLE level_attempts (
    id       INTEGER PRIMARY KEY,
    level_id INTEGER NOT NULL REFERENCES levels(id),
    chosen   TEXT NOT NULL,
    score    INTEGER NOT NULL,
    ts       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 错题本：答错收录，答对移除
CREATE TABLE wrongbook (
    question_id INTEGER PRIMARY KEY REFERENCES questions(id),
    wrong_count INTEGER NOT NULL DEFAULT 1,
    last_ts     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- 课文阅读记录（每打开一次一课记一行）
CREATE TABLE lesson_reads (
    chapter_id INTEGER NOT NULL REFERENCES chapters(id),
    ts         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def connect(db_path=None):
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()
