import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "presphere.db"


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _ensure(c, table, cols):
    c.execute(f"CREATE TABLE IF NOT EXISTS {table}(id INTEGER PRIMARY KEY AUTOINCREMENT)")
    have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    for name, typ in cols.items():
        if name not in have:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


def init():
    with conn() as c:
        _ensure(c, "attempts", {"ts": "REAL", "test_id": "TEXT", "subject": "TEXT", "score": "REAL",
                                "total": "REAL", "accuracy": "REAL", "seconds": "INTEGER"})
        _ensure(c, "responses", {"ts": "REAL", "test_id": "TEXT", "qid": "TEXT", "subject": "TEXT",
                                 "topic": "TEXT", "correct": "INTEGER"})
        _ensure(c, "evaluations", {"ts": "REAL", "question": "TEXT", "answer": "TEXT", "score": "REAL",
                                   "max_score": "REAL", "feedback": "TEXT", "features": "TEXT",
                                   "source": "TEXT", "score_frac": "REAL"})
        _ensure(c, "interview_evaluations", {"ts": "REAL", "question": "TEXT", "answer": "TEXT",
                                             "score": "REAL", "feedback": "TEXT"})
        c.execute("""CREATE TABLE IF NOT EXISTS question_stats(
            qid TEXT PRIMARY KEY, subject TEXT, topic TEXT,
            difficulty REAL, attempts INTEGER, correct INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS ability(
            subject TEXT PRIMARY KEY, theta REAL, n INTEGER)""")
        _ensure(c, "videos", {"ts": "REAL", "title": "TEXT", "subject": "TEXT",
            "filename": "TEXT", "original_name": "TEXT", "size": "INTEGER"})


        _ensure(c, "notes", {"ts": "REAL", "title": "TEXT", "subject": "TEXT", "content": "TEXT",
                             "filename": "TEXT", "original_name": "TEXT", "size": "INTEGER"})

        c.commit()
