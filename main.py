import csv
import hashlib
import hmac
import io
import math
import os
import random
import re
import secrets
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import llm
import ml
import seed_data

load_dotenv()

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
FRONTEND = BASE / "frontend"
UPLOADS = Path(os.getenv("DATA_DIR", str(BASE))) / "uploads"

app = FastAPI(title="PreSphere AI UPSC Platform")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

db.init()
seed_data.ensure(DATA)


# ---------------------------------------------------------------- auth
COOKIE = "ps_session"
SESSION_DAYS = 30
ADMIN_USER = os.getenv("ADMIN_USERNAME", "").strip()
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "")
_fails = {}


def _hash(pw, salt=None):
    salt = salt or secrets.token_bytes(16)
    return salt.hex() + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()


def _verify(pw, stored):
    try:
        salt, _ = (stored or "").split("$")
        return hmac.compare_digest(_hash(pw, bytes.fromhex(salt)), stored)
    except ValueError:
        return False


def _tok_hash(tok):
    return hashlib.sha256(tok.encode()).hexdigest()


def _start_session(response: Response, user_id):
    tok = secrets.token_urlsafe(32)
    with db.conn() as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        c.execute("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)",
                  (_tok_hash(tok), user_id, time.time() + SESSION_DAYS * 86400))
        c.commit()
    response.set_cookie(COOKIE, tok, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax")


def _user_from_request(request: Request):
    tok = request.cookies.get(COOKIE)
    if not tok:
        return None
    with db.conn() as c:
        row = c.execute("SELECT u.id, u.username, u.role FROM sessions s JOIN users u ON u.id=s.user_id "
                        "WHERE s.token=? AND s.expires>?", (_tok_hash(tok), time.time())).fetchone()
    return dict(row) if row else None


def current_user(request: Request):
    user = _user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in.")
    return user


def admin_user(user: dict = Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only the admin can do this.")
    return user


def _check_rate(key):
    now = time.time()
    recent = [t for t in _fails.get(key, []) if now - t < 300]
    _fails[key] = recent
    if len(recent) >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")


def seed_admin():
    if not ADMIN_USER or not ADMIN_PASS:
        print("WARNING: set ADMIN_USERNAME and ADMIN_PASSWORD in .env to create the admin account.")
        return
    with db.conn() as c:
        row = c.execute("SELECT id FROM users WHERE lower(username)=lower(?)", (ADMIN_USER,)).fetchone()
        if row:
            uid = row["id"]
            c.execute("UPDATE users SET pw=?, role='admin' WHERE id=?", (_hash(ADMIN_PASS), uid))
        else:
            uid = c.execute("INSERT INTO users(username,pw,role,ts) VALUES(?,?,?,?)",
                            (ADMIN_USER, _hash(ADMIN_PASS), "admin", time.time())).lastrowid
        for t in ("attempts", "responses", "evaluations", "interview_evaluations"):
            c.execute(f"UPDATE {t} SET user_id=? WHERE user_id IS NULL", (uid,))   # old data -> admin
        c.commit()


seed_admin()


class AuthIn(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register")
def register(payload: AuthIn, response: Response):
    u = payload.username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", u):
        raise HTTPException(status_code=400, detail="Username: 3-30 letters, numbers, dot, dash or underscore.")
    if not 6 <= len(payload.password) <= 128:
        raise HTTPException(status_code=400, detail="Password must be 6-128 characters.")
    if ADMIN_USER and u.lower() == ADMIN_USER.lower():
        raise HTTPException(status_code=400, detail="This username is not available.")
    with db.conn() as c:
        if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)", (u,)).fetchone():
            raise HTTPException(status_code=400, detail="Username already taken.")
        uid = c.execute("INSERT INTO users(username,pw,role,ts) VALUES(?,?,?,?)",
                        (u, _hash(payload.password), "student", time.time())).lastrowid
        c.commit()
    _start_session(response, uid)
    return {"user": {"username": u, "role": "student"}}


@app.post("/api/auth/login")
def login(payload: AuthIn, request: Request, response: Response):
    key = (request.client.host if request.client else "?") + "|" + payload.username.strip().lower()
    _check_rate(key)
    with db.conn() as c:
        row = c.execute("SELECT * FROM users WHERE lower(username)=lower(?)",
                        (payload.username.strip(),)).fetchone()
    if not row or not _verify(payload.password, row["pw"]):
        _fails.setdefault(key, []).append(time.time())
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    _start_session(response, row["id"])
    return {"user": {"username": row["username"], "role": row["role"]}}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(COOKIE)
    if tok:
        with db.conn() as c:
            c.execute("DELETE FROM sessions WHERE token=?", (_tok_hash(tok),))
            c.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    user = _user_from_request(request)
    return {"user": {"username": user["username"], "role": user["role"]} if user else None}


# ---------------------------------------------------------------- data helpers
_cache = {}


def load_csv(*names):
    for n in names:
        p = DATA / n
        if p.exists():
            m = p.stat().st_mtime
            if _cache.get(n, (0, None))[0] != m:
                with p.open("r", encoding="utf-8-sig", newline="") as f:
                    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
                            for r in csv.DictReader(f)]
                _cache[n] = (m, rows)
            return _cache[n][1]
    return []


def as_int(v, default=0):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return default


def slug(s):
    return re.sub(r"\W+", "-", s.lower(), flags=re.ASCII).strip("-")


def clean_options(row):
    return {"A": row.get("option_a", ""), "B": row.get("option_b", ""),
            "C": row.get("option_c", ""), "D": row.get("option_d", "")}


def normalise_answer(value, row=None):
    v = str(value or "").strip()
    m = re.fullmatch(r"\(?([A-Da-d])\)?[.)]?", v)
    if m:
        return m.group(1).upper()
    if row:
        for k, t in clean_options(row).items():
            if t and t.strip().lower() == v.lower():
                return k
    m = re.search(r"\b([ABCD])\b", v.upper())
    return m.group(1) if m else v.upper()


def get_mcqs():
    rows = load_csv("mcqs.csv", "upsc_mcqs.csv")
    seen = set()
    for i, q in enumerate(rows):
        qid = q.get("id") or f"Q{i + 1}"
        while qid in seen:
            qid += "_"
        seen.add(qid)
        q["id"] = qid
        q["subject"] = q.get("subject") or "General Studies"
        q["topic"] = q.get("topic") or "General"
    return rows


def get_mains():
    rows = load_csv("mains_questions.csv", "upsc_mains_questions.csv")
    for i, q in enumerate(rows):
        q["id"] = q.get("id") or f"MAIN{i + 1}"
    return rows


def get_subjects():
    out = {}
    for q in get_mcqs():
        out.setdefault(ml.norm(q["subject"]), q["subject"])
    return sorted(out.values())


def same_subject(q, subject):
    return ml.norm(q["subject"]) == ml.norm(subject)


def public_mcq(q):
    return {"id": q["id"], "subject": q["subject"], "topic": q["topic"],
            "difficulty": q.get("difficulty", "Medium"), "question": q.get("question", ""),
            "options": clean_options(q)}


# ---------------------------------------------------------------- schemas
class EvalIn(BaseModel):
    question: str
    answer: str
    word_limit: int = 150
    marks: int = 10


class ChatIn(BaseModel):
    message: str
    history: List[dict] = Field(default_factory=list)


class SubmitIn(BaseModel):
    test_id: str
    answers: Dict[str, str]
    seconds: int = 0


class InterviewIn(BaseModel):
    question: str
    answer: str


# ---------------------------------------------------------------- health / ml
@app.get("/api/health")
def health():
    return {"status": "ok", "ai": llm.available(), "message": "PreSphere backend is running"}


@app.get("/api/ml/status")
def ml_status(user: dict = Depends(admin_user)):
    with db.conn() as c:
        n_llm = c.execute("SELECT COUNT(*) n FROM evaluations WHERE source='llm'").fetchone()["n"]
        n_resp = c.execute("SELECT COUNT(*) n FROM responses").fetchone()["n"]
        n_users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    return {"llm_labelled_evaluations": n_llm, "mains_model_active": n_llm >= 25,
            "responses_logged": n_resp, "users": n_users}


# ---------------------------------------------------------------- MCQ / mains lists
@app.get("/api/mcqs")
def mcqs(subject: str = "all", n: int = 20, user: dict = Depends(current_user)):
    rows = get_mcqs()
    if subject.lower() != "all":
        rows = [q for q in rows if same_subject(q, subject)]
        chosen = ml.pick_adaptive(rows, max(1, n), user["id"])
    else:
        chosen = random.sample(rows, min(max(n, 1), len(rows))) if rows else []
    return [public_mcq(q) for q in chosen]


@app.get("/api/mains")
def mains(paper: str = "all", subject: str = "all", user: dict = Depends(current_user)):
    rows = get_mains()
    if paper.lower() != "all":
        rows = [q for q in rows if q.get("paper", "").lower() == paper.lower()]
    if subject.lower() != "all":
        rows = [q for q in rows if q.get("subject", "").lower() == subject.lower()]
    return [{"id": q["id"], "paper": q.get("paper", "GS"), "subject": q.get("subject", "General Studies"),
             "question": q.get("question", ""), "marks": as_int(q.get("marks"), 10),
             "word_limit": as_int(q.get("word_limit"), 150)} for q in rows]


# ---------------------------------------------------------------- mains evaluation
def _clean_criteria(crit):
    out = []
    if isinstance(crit, list):
        for c in crit:
            try:
                mx = float(c["max_score"])
                if mx > 0:
                    out.append({"label": str(c["label"]), "score": min(mx, max(0.0, float(c["score"]))),
                                "max_score": mx})
            except (KeyError, TypeError, ValueError):
                continue
    return out


def evaluate_answer(question, answer, word_limit, marks, user_id):
    meta = next((q for q in get_mains() if q.get("question") == question), {})
    kws = [k.strip() for k in re.split(r"[;|]", meta.get("keywords", "")) if k.strip()]
    feat = ml.mains_features(question, answer, word_limit, kws, meta.get("model_answer", ""))
    local = ml.mains_score(feat, marks)
    out, source, label = local, "ml", local["score"] / marks

    prompt = f"""Evaluate this UPSC Mains answer fairly.
Maximum marks: {marks}
Word limit: {word_limit}
Question: {question}
Candidate answer: {answer}
Return ONLY valid JSON with fields: score, summary, verdict, criteria, feedback.
criteria is a list of objects with label, score, max_score (labels: Content, Relevance, Structure, Presentation; max_scores sum to {marks}).
feedback is a list of improvement suggestions."""
    res = llm.ask_json("You are a strict UPSC Mains answer evaluator. Return only valid JSON.", prompt)
    if isinstance(res, dict):
        try:
            s = max(0.0, min(float(marks), float(res["score"])))
            final = round(0.75 * s + 0.25 * local["score"], 1)
            fb = res.get("feedback", [])
            fb = [str(x) for x in fb] if isinstance(fb, list) else [str(fb)]
            out = {"score": final, "max_score": marks, "verdict": ml.verdict(final / marks * 100),
                   "summary": str(res.get("summary") or local["summary"]),
                   "criteria": _clean_criteria(res.get("criteria")) or local["criteria"],
                   "feedback": fb or local["feedback"]}
            source, label = "llm", s / marks
        except (KeyError, TypeError, ValueError):
            pass
    ml.save_evaluation(question, answer, out["score"], marks, out["summary"], feat, source, label, user_id)
    return out


@app.post("/api/evaluate")
def evaluate(payload: EvalIn, user: dict = Depends(current_user)):
    if not payload.question.strip() or not payload.answer.strip():
        raise HTTPException(status_code=400, detail="Question and answer are required.")
    return evaluate_answer(payload.question, payload.answer, max(1, payload.word_limit),
                           max(1, payload.marks), user["id"])


@app.post("/api/mains/ocr")
async def mains_ocr(files: List[UploadFile] = File(...), user: dict = Depends(current_user)):
    mimes = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    images = []
    for f in files[:5]:
        mime = mimes.get(Path(f.filename or "").suffix.lower())
        if not mime:
            raise HTTPException(status_code=400, detail="Upload PNG, JPG or WEBP photos.")
        data = await f.read()
        if len(data) > 10 * 1048576:
            raise HTTPException(status_code=413, detail="Each photo must be under 10 MB.")
        images.append((data, mime))

    text = None
    if hasattr(llm, "ask_vision"):
        text = llm.ask_vision(
            "You transcribe handwritten exam answers accurately. Output only the transcribed text.",
            "Transcribe this handwritten answer exactly as written, keeping paragraphs and numbered points. "
            "Do not correct, summarise or add anything. Join multiple pages in order.",
            images)

    if not text:
        try:
            import pytesseract
            from PIL import Image
            text = "\n".join(pytesseract.image_to_string(Image.open(io.BytesIO(d))) for d, _ in images)
        except Exception:
            raise HTTPException(status_code=400,
                                detail="Reading photos needs a vision-capable LLM key (or pytesseract + Tesseract).")

    text = text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No readable text found. Use a clear, well-lit photo.")
    return {"text": text, "words": len(text.split())}


# ---------------------------------------------------------------- test series
def build_tests():
    rows = get_mcqs()
    tests = []
    if rows:
        n = min(20, len(rows))
        tests.append({"id": "prelims-mock", "title": "UPSC Prelims Practice Mock (mixed)", "type": "PRELIMS",
                      "count": n, "minutes": math.ceil(n * 1.2), "difficulty": "Adaptive",
                      "marks": n * 2, "subject": "all", "pyq": False})
    for subj in get_subjects():
        sub = [q for q in rows if same_subject(q, subj)]
        n = min(20, len(sub))
        tests.append({"id": slug(subj), "title": f"{subj} Practice Test", "type": "SUBJECT", "count": n,
                      "minutes": max(5, math.ceil(n * 1.2)), "difficulty": "Adaptive", "marks": n * 2,
                      "subject": subj, "pyq": False})
        pyq = [q for q in sub if q.get("year")]
        if pyq:
            n = min(25, len(pyq))
            tests.append({"id": slug(subj) + "-pyq", "title": f"{subj} — Previous Year Questions",
                          "type": "SUBJECT", "count": n, "minutes": max(5, math.ceil(n * 1.2)),
                          "difficulty": "PYQ", "marks": n * 2, "subject": subj, "pyq": True})
    return tests


def find_test(test_id):
    t = next((t for t in build_tests() if t["id"] == test_id), None)
    if not t:
        raise HTTPException(status_code=404, detail="Test not found.")
    return t


def test_pool(test):
    rows = get_mcqs()
    if test["subject"] == "all":
        return rows
    pool = [q for q in rows if same_subject(q, test["subject"])]
    return [q for q in pool if q.get("year")] if test["pyq"] else pool


@app.get("/api/tests")
def tests(user: dict = Depends(current_user)):
    return build_tests()


@app.get("/api/tests/{test_id}/questions")
def test_questions(test_id: str, user: dict = Depends(current_user)):
    uid = user["id"]
    test = find_test(test_id)
    pool = test_pool(test)
    if test["subject"] == "all":
        subs = get_subjects()
        per = max(1, test["count"] // max(1, len(subs)))
        chosen = []
        for s in subs:
            chosen += ml.pick_adaptive([q for q in pool if same_subject(q, s)], per, uid)
        rest = [q for q in pool if q not in chosen]
        if len(chosen) < test["count"]:
            chosen += ml.pick_adaptive(rest, test["count"] - len(chosen), uid)
        chosen = chosen[:test["count"]]
        random.shuffle(chosen)
    elif test["pyq"]:
        chosen = sorted(pool, key=lambda q: -as_int(q.get("year")))[:test["count"]]
    else:
        chosen = ml.pick_adaptive(pool, test["count"], uid)

    if test["subject"] != "all" and any(not same_subject(q, test["subject"]) for q in chosen):
        raise HTTPException(status_code=500, detail="Subject purity check failed.")

    out = []
    for q in chosen:
        item = public_mcq(q)
        item["answer"] = normalise_answer(q.get("answer", ""), q)
        item["explanation"] = q.get("explanation", "Review the relevant topic.")
        out.append(item)
    return out


@app.post("/api/tests/submit")
def submit_test(payload: SubmitIn, user: dict = Depends(current_user)):
    test = find_test(payload.test_id)
    by_id = {q["id"]: q for q in test_pool(test)}
    if any(k not in by_id for k in payload.answers):
        raise HTTPException(status_code=400,
                            detail="Submitted questions do not belong to this test's subject.")

    correct = wrong = skipped = 0
    review, log, subj_stats = [], [], {}
    for qid, raw in payload.answers.items():
        q = by_id[qid]
        selected = normalise_answer(raw, q) if raw else ""
        answer = normalise_answer(q.get("answer", ""), q)
        ok = bool(selected) and selected == answer
        if not selected:
            skipped += 1
        elif ok:
            correct += 1
        else:
            wrong += 1
        st = subj_stats.setdefault(q["subject"], {"correct": 0, "attempted": 0})
        if selected:
            st["attempted"] += 1
            st["correct"] += int(ok)
        log.append({"qid": qid, "subject": q["subject"], "topic": q["topic"],
                    "difficulty": q.get("difficulty", "Medium"), "attempted": bool(selected),
                    "correct": ok, "test_id": payload.test_id})
        review.append({"id": qid, "question": q.get("question", ""), "options": clean_options(q),
                       "selected": selected, "answer": answer, "correct": ok,
                       "explanation": q.get("explanation", "")})

    total = len(review)
    marks = correct * 2 - wrong * (2 / 3)
    attempted = correct + wrong
    accuracy = round(correct / attempted * 100, 1) if attempted else 0.0

    with db.conn() as c:
        c.execute("INSERT INTO attempts(ts,test_id,subject,score,total,accuracy,seconds,user_id) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (time.time(), payload.test_id, test["subject"], marks, total * 2, accuracy,
                   max(0, payload.seconds), user["id"]))
        c.commit()
    ml.record_responses(log, user["id"])

    return {"marks": round(marks, 2), "max_marks": total * 2, "correct": correct, "wrong": wrong,
            "skipped": skipped, "accuracy": accuracy, "review": review, "subject_stats": subj_stats}


# ---------------------------------------------------------------- interview
@app.get("/api/interview/questions")
def interview_questions(n: int = 5, user: dict = Depends(current_user)):
    rows = load_csv("interview_questions.csv")
    if not rows:
        rows = [{"id": "I001", "category": "Introduction",
                 "question": "Tell me about yourself and why you want to join the civil services."}]
    return random.sample(rows, min(max(1, n), len(rows)))


@app.post("/api/interview/evaluate")
def interview_evaluate(payload: InterviewIn, user: dict = Depends(current_user)):
    local = ml.interview_score(payload.question, payload.answer)
    overall, scores, feedback, follow = (local["overall"], local["scores"], local["feedback"],
                                         local["follow_up"])
    if payload.answer.strip():
        prompt = f"""Evaluate this UPSC interview practice response.
Question: {payload.question}
Answer: {payload.answer}
Return JSON with: overall (0-100), scores (object of category: score out of 10),
feedback (list), follow_up (string). Be constructive. Do not claim to measure voice or body language."""
        res = llm.ask_json("You are a UPSC interview board member. Return only valid JSON.", prompt)
        if isinstance(res, dict):
            try:
                o = max(0, min(100, as_int(res.get("overall"), overall)))
                sc = res.get("scores")
                if isinstance(sc, dict) and sc:
                    scores = {str(k): round(float(v), 1) for k, v in sc.items()}
                fb = res.get("feedback")
                if isinstance(fb, list) and fb:
                    feedback = [str(x) for x in fb]
                follow = str(res.get("follow_up") or follow)
                overall = round(0.7 * o + 0.3 * local["overall"])
            except (TypeError, ValueError):
                pass
    with db.conn() as c:
        c.execute("INSERT INTO interview_evaluations(ts,question,answer,score,feedback,user_id) VALUES(?,?,?,?,?,?)",
                  (time.time(), payload.question, payload.answer, overall,
                   "; ".join(map(str, feedback)), user["id"]))
        c.commit()
    return {"overall": overall, "scores": scores, "feedback": feedback, "follow_up": follow}


# ---------------------------------------------------------------- newspaper
def _read_upload(name, content):
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages)
        if name.endswith((".txt", ".md", ".csv")):
            return content.decode("utf-8", errors="ignore")
        if name.endswith((".png", ".jpg", ".jpeg")):
            try:
                import pytesseract
                from PIL import Image
                return pytesseract.image_to_string(Image.open(io.BytesIO(content)))
            except ImportError:
                raise HTTPException(status_code=400, detail="Image OCR needs: pip install pytesseract pillow "
                                                            "and the Tesseract binary. Upload a text PDF instead.")
        raise HTTPException(status_code=400, detail="Upload a PDF, TXT, MD, CSV (or PNG/JPG with OCR installed).")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}")


@app.post("/api/newspaper/analyze")
async def newspaper_analyze(file: UploadFile = File(...), user: dict = Depends(current_user)):
    text = _read_upload((file.filename or "").lower(), await file.read())
    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text found. Scanned PDFs need OCR first.")

    bank = get_mcqs()
    local = ml.analyze_news(text, bank)
    data = {"news_items": local["news_items"], "questions": local["questions"]}

    digest = " ".join(ml.top_sentences(text, 12))[:12000] or text[:12000]
    prompt = f"""Analyze this newspaper text for UPSC CSE.
Return JSON with news_items (list of objects: title, summary, tags) and questions (list of Mains questions).
Text:
{digest}"""
    res = llm.ask_json("You are a UPSC current-affairs analyst. Return only valid JSON.", prompt)
    if isinstance(res, dict):
        items = [{"title": str(i.get("title", ""))[:120], "summary": str(i.get("summary", ""))[:500],
                  "tags": [str(t) for t in i.get("tags", [])][:3] if isinstance(i.get("tags"), list) else []}
                 for i in res.get("news_items", []) if isinstance(i, dict) and i.get("title")]
        qs = [str(q) for q in res.get("questions", [])] if isinstance(res.get("questions"), list) else []
        if items:
            data["news_items"] = items
        if qs:
            data["questions"] = qs

    data["mcqs"] = [{"question": q.get("question", ""), "options": clean_options(q),
                     "answer": normalise_answer(q.get("answer", ""), q),
                     "explanation": q.get("explanation", "")} for q in local["mcq_rows"]]
    return data


# ---------------------------------------------------------------- doubt solver (RAG)
@app.post("/api/chat")
def chat(payload: ChatIn, user: dict = Depends(current_user)):
    docs, shown = [], []
    for r in load_csv("doubt_knowledge.csv"):
        t = " ".join(v for v in r.values() if v)
        docs.append(t)
        shown.append(t)
    for q in get_mcqs():
        docs.append(f"{q.get('question', '')} {q.get('explanation', '')}")
        shown.append(f"{q.get('question', '')}\n{q.get('explanation', '')}")
    hits = ml.retrieve(payload.message, docs, k=3)
    context = "\n".join(f"- {shown[i]}" for _, i in hits)

    prompt = (f"Reference notes (may be partially relevant):\n{context or 'none'}\n\n"
              f"Conversation: {payload.history[-6:]}\nStudent question: {payload.message}")
    answer = llm.ask("You are PreSphere AI, a UPSC preparation assistant. Give accurate, structured answers "
                     "with relevant Indian examples. Use the reference notes when relevant.", prompt)
    if not answer:
        if hits:
            answer = ("Offline knowledge-base match:\n\n" + "\n\n".join(shown[i] for _, i in hits[:2])
                      + "\n\nFor detailed AI answers, set a valid LLM API key in .env.")
        else:
            answer = ("I'm in offline mode and found no matching notes. Add more rows to "
                      "data/doubt_knowledge.csv or set a valid LLM API key in .env.")
    return {"reply": answer}


# ---------------------------------------------------------------- stats / revision
@app.get("/api/stats")
def stats(user: dict = Depends(current_user)):
    uid = user["id"]
    now = time.time()
    bank = get_mcqs()
    subjects = get_subjects()
    with db.conn() as c:
        att = c.execute("SELECT ts,seconds FROM attempts WHERE total IS NOT NULL AND user_id=?", (uid,)).fetchall()
        resp = c.execute("SELECT ts,subject,topic,correct FROM responses WHERE user_id=?", (uid,)).fetchall()
        evs = c.execute("SELECT ts,score,max_score FROM evaluations WHERE user_id=?", (uid,)).fetchall()
        n_int = c.execute("SELECT COUNT(*) AS n FROM interview_evaluations WHERE user_id=?", (uid,)).fetchone()["n"]

    def acc(rs):
        return round(sum(r["correct"] or 0 for r in rs) / len(rs) * 100, 1) if rs else 0.0

    def dy(ts):
        return datetime.fromtimestamp(ts).date()

    last7 = [r for r in resp if (r["ts"] or 0) >= now - 7 * 86400]
    prev7 = [r for r in resp if now - 14 * 86400 <= (r["ts"] or 0) < now - 7 * 86400]
    delta = round(acc(last7) - acc(prev7), 1) if last7 and prev7 else 0

    today = date.today()
    weekly = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        weekly.append({"label": day.strftime("%a"),
                       "accuracy": acc([r for r in resp if r["ts"] and dy(r["ts"]) == day])})

    active = {dy(r["ts"]) for r in resp if r["ts"]} | {dy(a["ts"]) for a in att if a["ts"]}
    streak, day = 0, (today if today in active else today - timedelta(days=1))
    while day in active:
        streak += 1
        day -= timedelta(days=1)

    secs_today = sum(a["seconds"] or 0 for a in att if a["ts"] and dy(a["ts"]) == today)
    secs_30 = sum(a["seconds"] or 0 for a in att if a["ts"] and a["ts"] >= now - 30 * 86400)

    strength = [{"subject": s, "accuracy": acc([r for r in resp if ml.norm(r["subject"]) == ml.norm(s)])}
                for s in subjects]
    done = {(ml.norm(r["subject"]), ml.norm(r["topic"])) for r in resp}
    total_topics = {(ml.norm(q["subject"]), ml.norm(q["topic"])) for q in bank}
    pcts = [e["score"] / e["max_score"] * 100 for e in evs if e["max_score"]]

    return {"accuracy": acc(resp), "accuracy_delta": delta, "questions_attempted": len(resp),
            "topics_completed": len(done), "topics_total": max(1, len(total_topics)),
            "study_hours_today": round(secs_today / 3600, 1), "study_hours_30d": round(secs_30 / 3600, 1),
            "streak": streak, "subject_strength": strength, "weekly": weekly,
            "mains_avg_pct": round(sum(pcts) / len(pcts), 1) if pcts else 0,
            "interviews_done": n_int, "answers_written": len(evs),
            "answers_this_week": sum(1 for e in evs if (e["ts"] or 0) >= now - 7 * 86400)}


@app.get("/api/revision")
def revision(user: dict = Depends(current_user)):
    bank = get_mcqs()
    subjects = get_subjects()
    mastery = ml.topic_mastery(user["id"])
    items = []
    for s in subjects:
        topics = sorted({q["topic"] for q in bank if same_subject(q, s)})
        seen = [(t, mastery[(ml.norm(s), ml.norm(t))]) for t in topics if (ml.norm(s), ml.norm(t)) in mastery]
        unseen = [t for t in topics if (ml.norm(s), ml.norm(t)) not in mastery]
        n_att = sum(v["attempts"] for _, v in seen)
        m = sum(v["acc"] * v["attempts"] for _, v in seen) / n_att if n_att else 0.0
        due = any(v["due"] for _, v in seen)
        if not n_att:
            priority = "medium"
        elif m < 0.5:
            priority = "high"
        elif m < 0.7 or due:
            priority = "medium"
        else:
            priority = "low"
        weak = [t for t, v in sorted(seen, key=lambda x: x[1]["acc"]) if v["acc"] < 0.7 or v["due"]][:3]
        items.append({"subject": s, "priority": priority, "attempts": n_att,
                      "topics": (weak or unseen[:3] or [s + " fundamentals"]),
                      "progress": round(m * 100, 1) if n_att else 0})

    attempted = [i for i in items if i["attempts"]]
    score = round(sum(i["progress"] for i in attempted) / len(attempted), 1) if attempted else 0

    weight = {"high": 3, "medium": 2, "low": 1}
    seq = [i for i in sorted(items, key=lambda i: -weight[i["priority"]]) for _ in range(weight[i["priority"]])]
    schedule = []
    for d in range(7):
        it = seq[d % len(seq)] if seq else {"subject": "General Studies", "topics": ["Fundamentals"]}
        schedule.append({"day": (date.today() + timedelta(days=d)).strftime("%a"),
                         "tasks": [f"Revise {it['subject']}: {it['topics'][0]}",
                                   f"Take a {it['subject']} subject test (10 MCQs)",
                                   "Review mistakes and key facts"]})

    weakest = min(attempted, key=lambda i: i["progress"]) if attempted else None
    rec = ({"title": f"Focus on {weakest['subject']} this week",
            "text": f"Your predicted mastery is {weakest['progress']}%. Revise: "
                    f"{', '.join(weakest['topics'])} and retake a subject test."}
           if weakest else
           {"title": "Start with a diagnostic test",
            "text": "Take a subject test so the ML engine can learn your strengths and weak topics."})
    return {"score": score, "high_count": sum(1 for i in items if i["priority"] == "high"),
            "items": items, "schedule": schedule, "recommendation": rec}


# ---------------------------------------------------------------- score summary
def _marks(correct, wrong):
    return round(correct * 2 - wrong * (2 / 3), 2)


@app.get("/api/score-summary")
def score_summary(user: dict = Depends(current_user)):
    uid = user["id"]
    names = {ml.norm(s): s for s in get_subjects()}
    titles = {t["id"]: t["title"] for t in build_tests()}
    with db.conn() as c:
        resp = c.execute("SELECT subject,topic,correct FROM responses WHERE user_id=?", (uid,)).fetchall()
        att = c.execute("SELECT ts,test_id,subject,score,total,accuracy FROM attempts "
                        "WHERE total IS NOT NULL AND user_id=? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
        n_tests = c.execute("SELECT COUNT(*) n FROM attempts WHERE total IS NOT NULL AND user_id=?",
                            (uid,)).fetchone()["n"]

    agg = {}
    for r in resp:
        key = ml.norm(r["subject"])
        s = agg.setdefault(key, {"subject": names.get(key, r["subject"]), "correct": 0, "wrong": 0, "topics": {}})
        t = s["topics"].setdefault(r["topic"] or "General", {"correct": 0, "wrong": 0})
        k = "correct" if r["correct"] else "wrong"
        s[k] += 1
        t[k] += 1

    subjects = []
    for s in sorted(agg.values(), key=lambda x: x["subject"]):
        n = s["correct"] + s["wrong"]
        subjects.append({
            "subject": s["subject"], "attempted": n, "correct": s["correct"], "wrong": s["wrong"],
            "marks": _marks(s["correct"], s["wrong"]), "max_marks": n * 2,
            "accuracy": round(s["correct"] / n * 100, 1) if n else 0,
            "topics": [{"topic": k, "attempted": v["correct"] + v["wrong"], "correct": v["correct"],
                        "wrong": v["wrong"], "marks": _marks(v["correct"], v["wrong"]),
                        "max_marks": (v["correct"] + v["wrong"]) * 2}
                       for k, v in sorted(s["topics"].items())]})

    correct = sum(s["correct"] for s in subjects)
    wrong = sum(s["wrong"] for s in subjects)
    n = correct + wrong
    return {
        "total_questions": n, "correct": correct, "wrong": wrong,
        "total_marks": _marks(correct, wrong), "max_marks": n * 2,
        "accuracy": round(correct / n * 100, 1) if n else 0, "tests_taken": n_tests,
        "subjects": subjects,
        "recent_tests": [{"title": titles.get(a["test_id"], a["test_id"]), "subject": a["subject"],
                          "score": round(a["score"] or 0, 2), "total": a["total"],
                          "accuracy": a["accuracy"],
                          "date": datetime.fromtimestamp(a["ts"]).strftime("%d %b %Y, %H:%M") if a["ts"] else ""}
                         for a in att],
    }


# ---------------------------------------------------------------- video (admin uploads, students watch)
VIDEO_DIR = UPLOADS / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".ogg", ".m4v"}
MAX_VIDEO_MB = 500


def _video_row(r):
    return {"id": r["id"], "title": r["title"], "subject": r["subject"],
            "url": f"/media/videos/{r['filename']}", "size_mb": round((r["size"] or 0) / 1048576, 1),
            "date": datetime.fromtimestamp(r["ts"]).strftime("%d %b %Y") if r["ts"] else ""}


@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...), title: str = Form(""), subject: str = Form("General"),
                       user: dict = Depends(admin_user)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(status_code=400, detail="Upload an mp4, webm, mov, mkv, ogg or m4v video.")
    name = f"{uuid.uuid4().hex}{ext}"
    dest = VIDEO_DIR / name
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_MB * 1048576:
                    raise HTTPException(status_code=413, detail=f"Video is larger than {MAX_VIDEO_MB} MB.")
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    with db.conn() as c:
        cur = c.execute("INSERT INTO videos(ts,title,subject,filename,original_name,size) VALUES(?,?,?,?,?,?)",
                        (time.time(), title.strip() or file.filename, subject.strip() or "General",
                         name, file.filename, size))
        c.commit()
        row = c.execute("SELECT * FROM videos WHERE id=?", (cur.lastrowid,)).fetchone()
    return _video_row(row)


@app.get("/api/videos")
def list_videos(subject: str = "all", user: dict = Depends(current_user)):
    with db.conn() as c:
        rows = c.execute("SELECT * FROM videos ORDER BY id DESC").fetchall()
    if subject.lower() != "all":
        rows = [r for r in rows if ml.norm(r["subject"]) == ml.norm(subject)]
    return [_video_row(r) for r in rows]


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: int, user: dict = Depends(admin_user)):
    with db.conn() as c:
        row = c.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Video not found.")
        c.execute("DELETE FROM videos WHERE id=?", (video_id,))
        c.commit()
    (VIDEO_DIR / row["filename"]).unlink(missing_ok=True)
    return {"deleted": video_id}


# ---------------------------------------------------------------- notes (admin writes, students read)
NOTES_DIR = UPLOADS / "notes"
NOTES_DIR.mkdir(parents=True, exist_ok=True)
NOTE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".md", ".docx", ".pptx"}
MAX_NOTE_MB = 500


def _note_row(r):
    fn = r["filename"] or ""
    return {"id": r["id"], "title": r["title"], "subject": r["subject"], "content": r["content"] or "",
            "url": f"/media/notes/{fn}" if fn else "", "file_name": r["original_name"] or "",
            "ext": Path(fn).suffix.lower() if fn else "",
            "size_mb": round((r["size"] or 0) / 1048576, 2),
            "date": datetime.fromtimestamp(r["ts"]).strftime("%d %b %Y") if r["ts"] else ""}


@app.post("/api/notes")
async def add_note(title: str = Form(""), subject: str = Form("General"), content: str = Form(""),
                   file: Optional[UploadFile] = File(None), user: dict = Depends(admin_user)):
    has_file = bool(file and file.filename)
    if not content.strip() and not has_file:
        raise HTTPException(status_code=400, detail="Write some notes or attach a file.")

    name, orig, size = "", "", 0
    if has_file:
        ext = Path(file.filename).suffix.lower()
        if ext not in NOTE_EXT:
            raise HTTPException(status_code=400, detail="Allowed files: " + ", ".join(sorted(NOTE_EXT)))
        name, orig = f"{uuid.uuid4().hex}{ext}", file.filename
        dest = NOTES_DIR / name
        try:
            with dest.open("wb") as out:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_NOTE_MB * 1048576:
                        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_NOTE_MB} MB.")
                    out.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise

    first_line = content.strip().splitlines()[0][:60] if content.strip() else ""
    final_title = title.strip() or orig or first_line or "Untitled note"
    with db.conn() as c:
        cur = c.execute("INSERT INTO notes(ts,title,subject,content,filename,original_name,size) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (time.time(), final_title, subject.strip() or "General", content.strip(),
                         name, orig, size))
        c.commit()
        row = c.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone()
    return _note_row(row)


@app.get("/api/notes/subjects")
def note_subjects(user: dict = Depends(current_user)):
    with db.conn() as c:
        rows = c.execute("SELECT subject, COUNT(*) AS n FROM notes GROUP BY subject").fetchall()
    counts, names = {}, {}
    for r in rows:
        k = ml.norm(r["subject"])
        counts[k] = counts.get(k, 0) + r["n"]
        names.setdefault(k, r["subject"])
    for s in get_subjects():
        names.setdefault(ml.norm(s), s)
    return {"total": sum(counts.values()),
            "subjects": [{"subject": names[k], "count": counts.get(k, 0)}
                         for k in sorted(names, key=lambda k: names[k].lower())]}


@app.get("/api/notes")
def list_notes(subject: str = "all", user: dict = Depends(current_user)):
    with db.conn() as c:
        rows = c.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    if subject.lower() != "all":
        rows = [r for r in rows if ml.norm(r["subject"]) == ml.norm(subject)]
    return [_note_row(r) for r in rows]


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: dict = Depends(admin_user)):
    with db.conn() as c:
        row = c.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Note not found.")
        c.execute("DELETE FROM notes WHERE id=?", (note_id,))
        c.commit()
    if row["filename"]:
        (NOTES_DIR / row["filename"]).unlink(missing_ok=True)
    return {"deleted": note_id}


# ---------------------------------------------------------------- static files (keep LAST)
app.mount("/media", StaticFiles(directory=str(UPLOADS)), name="media")

if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")