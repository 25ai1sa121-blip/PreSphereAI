
import json
import math
import random
import re
import time
from collections import Counter, defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.pipeline import make_pipeline

import db


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def sig(x):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def words(t):
    return re.findall(r"[A-Za-z']+", t or "")


def sentences(text, min_len=25):
    out, seen = [], set()
    for s in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        s = s.strip()
        if len(s) >= min_len and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    return out


def retrieve(query, docs, k=3, min_score=0.08):
    if not docs or not (query or "").strip():
        return []
    try:
        X = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit_transform(docs + [query])
    except ValueError:
        return []
    sims = cosine_similarity(X[-1], X[:-1]).ravel()
    return [(float(sims[i]), int(i)) for i in np.argsort(-sims)[:k] if sims[i] >= min_score]


# ===================== ADAPTIVE TEST ENGINE =====================
DIFF_PRIOR = {"easy": -1.0, "medium": 0.0, "hard": 1.0}


def record_responses(items):
    """items: dicts with qid, subject, topic, difficulty, attempted, correct, test_id."""
    now = time.time()
    with db.conn() as c:
        for it in items:
            if not it["attempted"]:
                continue
            y = 1.0 if it["correct"] else 0.0
            c.execute("INSERT INTO responses(ts,test_id,qid,subject,topic,correct) VALUES(?,?,?,?,?,?)",
                      (now, it["test_id"], it["qid"], it["subject"], it["topic"], int(y)))
            qs = c.execute("SELECT * FROM question_stats WHERE qid=?", (it["qid"],)).fetchone()
            b = qs["difficulty"] if qs else DIFF_PRIOR.get(norm(it["difficulty"]), 0.0)
            n = qs["attempts"] if qs else 0
            nc = qs["correct"] if qs else 0
            ab = c.execute("SELECT theta,n FROM ability WHERE subject=?", (it["subject"],)).fetchone()
            theta, na = (ab["theta"], ab["n"]) if ab else (0.0, 0)
            p = sig(theta - b)
            theta += 0.4 / math.sqrt(1 + na / 5) * (y - p)
            b -= 0.2 / math.sqrt(1 + n / 3) * (y - p)
            c.execute("INSERT OR REPLACE INTO question_stats VALUES(?,?,?,?,?,?)",
                      (it["qid"], it["subject"], it["topic"], b, n + 1, nc + int(y)))
            c.execute("INSERT OR REPLACE INTO ability VALUES(?,?,?)", (it["subject"], theta, na + 1))
        c.commit()


def topic_mastery(half_life_days=7.0):
    """Recency-weighted, Beta-smoothed topic accuracy + forgetting-curve retention."""
    now = time.time()
    with db.conn() as c:
        rows = c.execute("SELECT ts,subject,topic,correct FROM responses").fetchall()
    agg = defaultdict(lambda: [0.0, 0.0, 0, 0.0, 0])
    for r in rows:
        ts = r["ts"] or now
        w = 0.5 ** ((now - ts) / (half_life_days * 86400))
        a = agg[(norm(r["subject"]), norm(r["topic"]))]
        a[0] += w * (r["correct"] or 0)
        a[1] += w
        a[2] += 1
        a[3] = max(a[3], ts)
        a[4] += r["correct"] or 0
    out = {}
    for k, (wc, wa, n, last, nc) in agg.items():
        stability = 2.0 * (1 + nc)
        ret = math.exp(-((now - last) / 86400) / stability)
        out[k] = {"acc": (wc + 1) / (wa + 2), "attempts": n, "retention": ret, "due": ret < 0.6}
    return out


def pick_adaptive(rows, n):
    """Choose n questions: target ~65% success probability, favour weak topics, avoid recent repeats."""
    rows = list(rows)
    if len(rows) <= n:
        random.shuffle(rows)
        return rows
    with db.conn() as c:
        qs = {r["qid"]: r["difficulty"] for r in c.execute("SELECT qid,difficulty FROM question_stats")}
        ab = {r["subject"]: r["theta"] for r in c.execute("SELECT subject,theta FROM ability")}
        seen = {r["qid"]: r["t"] for r in c.execute("SELECT qid,MAX(ts) t FROM responses GROUP BY qid")}
    mastery = topic_mastery()
    now = time.time()
    scored = []
    for q in rows:
        b = qs.get(q["id"], DIFF_PRIOR.get(norm(q.get("difficulty")), 0.0))
        p = sig(ab.get(q["subject"], 0.0) - b)
        weak = 1 - mastery.get((norm(q["subject"]), norm(q["topic"])), {"acc": 0.5})["acc"]
        age = (now - seen[q["id"]]) / 86400 if q["id"] in seen else 99
        pen = 0.8 if age < 2 else 0.4 if age < 7 else 0.0
        scored.append((-abs(p - 0.65) * 1.5 + 0.8 * weak - pen + random.random() * 0.35, q))
    scored.sort(key=lambda t: -t[0])
    return [q for _, q in scored[:n]]


# ===================== SUBJECT CLASSIFIER + NEWS =====================
LEX = {k: set(v.split()) for k, v in {
    "Polity": "constitution parliament supreme court article amendment election governor president federal fundamental rights bill judiciary legislature",
    "Governance": "governance policy scheme ministry digital egovernance transparency accountability civil services reform welfare panchayat",
    "Economy": "gdp inflation rbi repo fiscal budget tax gst trade export import banking investment growth deficit msme subsidy",
    "International Relations": "bilateral summit treaty united nations g20 brics quad foreign diplomacy sanctions neighbour agreement",
    "Environment": "climate emission biodiversity forest pollution wildlife carbon renewable cop conservation ecosystem",
    "Science & Technology": "satellite isro ai artificial intelligence quantum biotechnology vaccine semiconductor space technology research drone",
    "Geography": "monsoon river cyclone earthquake mountain soil glacier ocean mineral drought flood",
    "History": "ancient medieval freedom movement dynasty heritage temple archaeology colonial",
    "Society": "women education poverty health tribal caste urbanisation migration inequality",
    "Security": "terrorism defence army navy cyber insurgency naxal border security military",
    "Ethics": "integrity ethics ethical corruption conduct moral values probity",
}.items()}


def paper_for(subject):
    s = norm(subject)
    if re.search(r"polity|governance|international|relation|justice", s):
        return "GS-II"
    if re.search(r"econom|environment|science|technolog|security|agri", s):
        return "GS-III"
    if re.search(r"histor|geograph|society|culture|art", s):
        return "GS-I"
    if "ethic" in s:
        return "GS-IV"
    return "GS"


def lex_label(text):
    toks = set(re.findall(r"[a-z]+", text.lower()))
    best, score = None, 0
    for s, kw in LEX.items():
        sc = len(toks & kw)
        if sc > score:
            best, score = s, sc
    return best, score


_SM = {"sig": None, "model": None}


def subject_model(bank):
    texts = [f'{q.get("question", "")} {q.get("topic", "")} {q.get("explanation", "")}' for q in bank]
    labels = [q.get("subject", "") for q in bank]
    key = (len(texts), len(set(labels)))
    if _SM["sig"] == key:
        return _SM["model"]
    model = None
    if len(texts) >= 8 and len(set(labels)) >= 2:
        model = make_pipeline(TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True),
                              LogisticRegression(max_iter=1000, C=5))
        model.fit(texts, labels)
    _SM.update(sig=key, model=model)
    return model


def label_text(text, model):
    lab, _ = lex_label(text)
    if model is not None:
        proba = model.predict_proba([text])[0]
        i = int(np.argmax(proba))
        if proba[i] >= 0.5 or not lab:
            return str(model.classes_[i]), float(proba[i])
    return lab or "General Studies", 0.3


def top_sentences(text, k=6):
    sents = sentences(text)
    if len(sents) <= k:
        return sents
    try:
        X = TfidfVectorizer(stop_words="english").fit_transform(sents)
    except ValueError:
        return sents[:k]
    S = cosine_similarity(X)
    np.fill_diagonal(S, 0)
    n = len(sents)
    rank = np.ones(n) / n
    rows = S.sum(1, keepdims=True)
    rows[rows == 0] = 1
    M = S / rows
    for _ in range(40):  # TextRank power iteration
        rank = 0.15 / n + 0.85 * (M.T @ rank)
    boost = np.array([1 + 0.5 * min(1, lex_label(s)[1] / 3) for s in sents])
    idx = sorted(np.argsort(-(rank * boost))[:k])
    return [sents[i] for i in idx]


def key_phrases(text, n=8):
    sents = sentences(text, 15) or [text]
    for ngram in ((2, 2), (1, 1)):
        try:
            v = TfidfVectorizer(stop_words="english", ngram_range=ngram,
                                token_pattern=r"(?u)\b[A-Za-z][A-Za-z]{2,}\b")
            X = v.fit_transform(sents)
        except ValueError:
            continue
        scores = np.asarray(X.sum(axis=0)).ravel()
        terms = v.get_feature_names_out()
        out, used = [], set()
        for i in np.argsort(-scores):
            ws = set(terms[i].split())
            if ws & used:
                continue
            out.append(terms[i])
            used |= ws
            if len(out) >= n:
                break
        if out:
            return out
    return []


TEMPLATES = [
    "Critically examine the significance of {p} in the context of {s}. (150 words)",
    "Discuss the challenges and way forward regarding {p}. (150 words)",
    "{p} has emerged as a key issue in recent times. Analyse its implications for India. (250 words)",
    "Evaluate the role of government policy in addressing {p}. (150 words)",
]


def gen_questions(phrases, subject, n=5):
    qs = []
    for p in random.sample(phrases, min(n, len(phrases))):
        qs.append(random.choice(TEMPLATES).format(p=p, s=subject))
    return qs


def related_mcqs(text, bank, dominant, k=5):
    docs = [f"{q.get('question', '')} {q.get('topic', '')} {q.get('explanation', '')}" for q in bank]
    rows = [bank[i] for _, i in retrieve(text[:6000], docs, k=k, min_score=0.03)]
    if len(rows) < 3:
        pool = [q for q in bank if norm(q.get("subject")) == norm(dominant)] or bank
        rows += [q for q in random.sample(pool, min(len(pool), k)) if q not in rows]
    return rows[:k]


def analyze_news(text, bank, k=6):
    model = subject_model(bank)
    items, counts = [], Counter()
    for s in top_sentences(text, k):
        subj, _ = label_text(s, model)
        counts[subj] += 1
        title = s if len(s) <= 90 else s[:90].rsplit(" ", 1)[0] + "…"
        items.append({"title": title, "summary": s[:500], "tags": [paper_for(subj), subj]})
    dominant = counts.most_common(1)[0][0] if counts else "General Studies"
    return {"news_items": items,
            "questions": gen_questions(key_phrases(text, 10), dominant),
            "mcq_rows": related_mcqs(text, bank, dominant),
            "dominant": dominant}


# ===================== MAINS EVALUATION =====================
CONNECT = ("however", "therefore", "thus", "hence", "moreover", "furthermore", "on the other hand",
           "in conclusion", "way forward", "for instance", "for example", "consequently", "while")
EVID = re.compile(r"\b(article\s*\d+|19\d\d|20\d\d|act|committee|commission|report|scheme|mission|"
                  r"supreme court|survey|index|ministry|policy|case)\b|\d+\s*%|per cent", re.I)
FEATURES = ["len_ratio", "len_fit", "relevance", "kw_cov", "connectives", "evidence",
            "diversity", "sent_fit", "paragraphs", "has_intro", "has_conclusion"]


def mains_features(question, answer, word_limit=150, keywords=None, model_answer=""):
    keywords = keywords or []
    w = words(answer)
    n = len(w)
    ratio = n / max(1, word_limit)
    if ratio < 0.95:
        len_fit = ratio / 0.95
    elif ratio <= 1.1:
        len_fit = 1.0
    else:
        len_fit = max(0.0, 1 - (ratio - 1.1) / 0.6)
    ref = " ".join([question, " ".join(keywords), model_answer])
    try:
        X = TfidfVectorizer(stop_words="english", sublinear_tf=True).fit_transform([ref, answer])
        cos = float(cosine_similarity(X[0], X[1])[0, 0])
    except ValueError:
        cos = 0.0
    relevance = min(1.0, cos * (2.0 if model_answer else 2.8))
    low = answer.lower()
    missing = [k for k in keywords if k.lower() not in low]
    kw_cov = (1 - len(missing) / len(keywords)) if keywords else relevance
    conn = min(1.0, sum(low.count(c) for c in CONNECT) / 4)
    evidence = min(1.0, len(EVID.findall(answer)) / 4)
    diversity = min(1.0, (len({x.lower() for x in w}) / n) / 0.65) if n else 0.0
    sents = sentences(answer, 5)
    m = n / max(1, len(sents)) if sents else 0
    sent_fit = max(0.0, 1 - max(0, 10 - m, m - 28) / 20) if sents else 0.0
    paras = len([p for p in re.split(r"\n+", answer) if p.strip()])
    paragraphs = min(1.0, paras / 3 + (0.34 if re.search(r"^\s*(\d+[.)]|[-•*])", answer, re.M) else 0))
    q_tokens = {x.lower() for x in words(question) if len(x) > 3}
    first = {x.lower() for x in w[:25]}
    has_intro = 1.0 if len(q_tokens & first) >= 2 else 0.4
    tail = " ".join(w[-40:]).lower()
    has_conclusion = 1.0 if re.search(r"\b(conclusion|way forward|thus|hence|overall|to sum up)\b", tail) else 0.3
    return {"len_ratio": ratio, "len_fit": len_fit, "relevance": relevance, "kw_cov": kw_cov,
            "connectives": conn, "evidence": evidence, "diversity": diversity, "sent_fit": sent_fit,
            "paragraphs": paragraphs, "has_intro": has_intro, "has_conclusion": has_conclusion,
            "missing": missing, "n": n}


_MM = {"n": -1, "model": None}


def _mains_model():
    try:
        with db.conn() as c:
            rows = c.execute("SELECT features,score_frac FROM evaluations WHERE source='llm' "
                             "AND features IS NOT NULL AND score_frac IS NOT NULL").fetchall()
        if len(rows) < 25:
            return None
        if _MM["n"] == len(rows):
            return _MM["model"]
        X = np.array([json.loads(r["features"]) for r in rows])
        y = np.array([r["score_frac"] for r in rows])
        _MM.update(n=len(rows), model=Ridge(alpha=2.0).fit(X, y))
        return _MM["model"]
    except Exception:
        return None


def verdict(pct):
    return ("Excellent answer" if pct >= 70 else "Good answer" if pct >= 55
            else "Average answer" if pct >= 40 else "Needs improvement")


FB = {"Content": "Add specific facts: committee/report names, data, constitutional articles, schemes.",
      "Relevance": "Address the exact directive of the question and reuse its key terms in intro and body.",
      "Structure": "Use a short intro, 3-4 sub-headed body points and a forward-looking conclusion.",
      "Presentation": "Keep sentences crisp (10-25 words) and stay close to the word limit."}


def mains_score(f, marks):
    parts = {"Content": (0.4 * f["kw_cov"] + 0.35 * f["evidence"] + 0.25 * f["len_fit"], 0.3),
             "Relevance": (0.7 * f["relevance"] + 0.3 * f["kw_cov"], 0.3),
             "Structure": (0.3 * f["has_intro"] + 0.3 * f["has_conclusion"] + 0.2 * f["paragraphs"]
                           + 0.2 * f["connectives"], 0.2),
             "Presentation": (0.4 * f["sent_fit"] + 0.3 * f["diversity"] + 0.3 * f["len_fit"], 0.2)}
    raw = sum(min(1, v) * w for v, w in parts.values())
    if f["n"] == 0:
        raw = 0.0
    elif f["len_ratio"] < 0.2:
        raw *= 0.6
    frac = raw
    model = _mains_model()
    if model is not None and f["n"]:
        try:
            frac = 0.5 * raw + 0.5 * float(np.clip(model.predict([[f[k] for k in FEATURES]])[0], 0, 1))
        except Exception:
            pass
    frac = float(np.clip(frac, 0, 1))
    scale = frac / raw if raw > 0 else 0
    crit = []
    for label, (v, w) in parts.items():
        mx = round(marks * w, 1)
        crit.append({"label": label, "score": round(min(mx, min(1, v) * w * marks * scale), 1), "max_score": mx})
    weakest = sorted(parts, key=lambda k: parts[k][0])[:2]
    fb = [FB[k] for k in weakest]
    if f["missing"]:
        fb.append("Consider covering: " + ", ".join(f["missing"][:5]) + ".")
    if f["len_ratio"] > 1.1:
        fb.append("You exceeded the word limit; trim repetition.")
    elif f["len_ratio"] < 0.6:
        fb.append("The answer is short; expand with analysis and examples.")
    if f["n"] == 0:
        fb = ["Write an answer addressing the question."]
    return {"score": round(frac * marks, 1), "max_score": marks, "verdict": verdict(frac * 100),
            "summary": "ML-based evaluation (relevance, coverage, structure, style).",
            "criteria": crit, "feedback": fb}


def save_evaluation(question, answer, score, max_score, summary, feat, source, label):
    with db.conn() as c:
        c.execute("INSERT INTO evaluations(ts,question,answer,score,max_score,feedback,features,source,score_frac) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  (time.time(), question, answer, score, max_score, summary,
                   json.dumps([feat[k] for k in FEATURES]), source, label))
        c.commit()


# ===================== INTERVIEW =====================
FILLERS = {"um", "uh", "basically", "actually", "like", "literally"}


def interview_score(question, answer):
    w = words(answer)
    n = len(w)
    if n == 0:
        return {"overall": 0, "scores": {"Clarity": 0, "Structure": 0, "Relevance": 0, "Depth": 0},
                "feedback": ["Please provide an answer to evaluate."],
                "follow_up": "Could you start by stating your position clearly?"}
    sents = sentences(answer, 5) or [answer]
    m = n / len(sents)
    filler = sum(1 for x in w if x.lower() in FILLERS) / n
    clarity = max(0.0, 1 - max(0, 10 - m, m - 28) / 20) * (1 - min(0.5, filler * 5))
    low = answer.lower()
    enum = sum(low.count(x) for x in ("first", "second", "finally", "firstly", "secondly", "lastly", "because"))
    structure = min(1.0, (enum + (1 if n >= 60 else 0) + (1 if len(sents) >= 3 else 0)) / 4)
    try:
        X = TfidfVectorizer(stop_words="english").fit_transform([question, answer])
        cos = float(cosine_similarity(X[0], X[1])[0, 0])
    except ValueError:
        cos = 0.0
    relevance = min(1.0, cos * 4 + (0.25 if n >= 20 else 0))
    examples = len(EVID.findall(answer)) + sum(low.count(x) for x in ("for example", "for instance", "in my experience"))
    depth = 0.6 * min(1.0, examples / 3) + 0.4 * min(1.0, n / 120)
    sc = {"Clarity": clarity, "Structure": structure, "Relevance": relevance, "Depth": depth}
    msgs = {"Clarity": "Use shorter, direct sentences and avoid filler words.",
            "Structure": "Organise your answer into clear points (first, second, finally).",
            "Relevance": "Answer the exact question asked before adding extra points.",
            "Depth": "Support your view with a concrete example, data point or experience."}
    fb = [msgs[k] for k in sorted(sc, key=sc.get)[:2]]
    if n < 30:
        fb.append("Expand your answer; boards expect 45-60 seconds of reasoning.")
    kp = key_phrases(answer, 1)
    follow = (f"You mentioned {kp[0]}. How would you implement this at the ground level?"
              if kp else "Can you support your answer with a practical example?")
    return {"overall": round(sum(sc.values()) / 4 * 100),
            "scores": {k: round(v * 10, 1) for k, v in sc.items()}, "feedback": fb, "follow_up": follow}

