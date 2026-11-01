
const API_BASE_URL = window.location.origin;

// const API_BASE_URL = "http://localhost:8000";
 
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
 
function escapeHTML(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
}
 
async function api(path, opts = {}) {
    const res = await fetch(API_BASE_URL + path, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Request failed (${res.status})`);
    }
    return res.json();
}
 
const post = (path, body) =>
    api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
 
const fmtTime = s => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
 
const toast = $("#toast");
let toastTimer = null;
 
function showToast(message) {
    toast.querySelector("span").textContent = message;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 2800);
}
 
function backendError(err) {
    showToast("Backend error: " + err.message);
}
 
 
/* =========================================
   NAVIGATION
========================================= */
 
const navLinks = $$(".nav-link");
const pages = $$(".page");
const menuBtn = $("#menuBtn");
const sidebar = $("#sidebar");
 
const pageLoaders = {};   // filled further down
 
function showPage(name) {
    pages.forEach(p => p.classList.remove("active-page"));
    $("#" + name)?.classList.add("active-page");
 
    navLinks.forEach(l => {
        const on = l.dataset.page === name;
        l.classList.toggle("active", on);
        on ? l.setAttribute("aria-current", "page") : l.removeAttribute("aria-current");
    });
 
    window.scrollTo({ top: 0, behavior: "smooth" });
    sidebar.classList.remove("open");
    menuBtn.setAttribute("aria-expanded", "false");
 
    pageLoaders[name]?.();
}
 
navLinks.forEach(l => l.addEventListener("click", e => {
    e.preventDefault();
    showPage(l.dataset.page);
}));
 
$$("[data-go]").forEach(el => {
    el.addEventListener("click", e => { e.preventDefault(); showPage(el.dataset.go); });
    if (el.tagName !== "BUTTON" && el.tagName !== "A") {
        el.setAttribute("role", "button");
        el.setAttribute("tabindex", "0");
        el.addEventListener("keydown", e => {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showPage(el.dataset.go); }
        });
    }
});
 
menuBtn.setAttribute("aria-expanded", "false");
menuBtn.setAttribute("aria-controls", "sidebar");
menuBtn.addEventListener("click", () => {
    menuBtn.setAttribute("aria-expanded", String(sidebar.classList.toggle("open")));
});
document.addEventListener("keydown", e => {
    if (e.key === "Escape" && sidebar.classList.contains("open")) {
        sidebar.classList.remove("open");
        menuBtn.setAttribute("aria-expanded", "false");
        menuBtn.focus();
    }
});
 
 
/* =========================================
   DASHBOARD
========================================= */
 
async function loadDashboard() {
    try {
        const [s, r] = await Promise.all([api("/api/stats"), api("/api/revision")]);
 
        $("#dashScore").textContent = Math.round(s.accuracy) + "%";
        const d = $("#dashDelta");
        d.textContent = s.questions_attempted
            ? `${s.accuracy_delta >= 0 ? "↑" : "↓"} ${Math.abs(s.accuracy_delta)}% vs last week`
            : "Take a test to begin";
        d.className = s.accuracy_delta >= 0 && s.questions_attempted ? "positive" : "";
        $("#dashTopics").textContent = s.topics_completed;
        $("#dashTopicsOf").textContent = `of ${s.topics_total} topics`;
        $("#dashStudy").textContent = s.study_hours_today + "h";
        $("#dashStreak").textContent = s.streak + (s.streak === 1 ? " Day" : " Days");
 
        $("#dashBars").innerHTML = s.subject_strength.map(x => `
            <div class="bar-item">
                <span>${escapeHTML(x.subject)}</span>
                <div><i style="height:${x.accuracy}%"></i></div>
                <b>${x.accuracy}%</b>
            </div>`).join("");
 
        const tasks = r.schedule[0].tasks;
        $("#dashTasksSub").textContent = `${tasks.length} tasks today`;
        $("#dashTasks").innerHTML = tasks.map(t => `
            <label class="task"><input type="checkbox"><span>${escapeHTML(t)}</span></label>`).join("");
        $$("#dashTasks .task input").forEach(box => box.addEventListener("change", () => {
            box.closest(".task").classList.toggle("completed", box.checked);
            if (box.checked) showToast("Task completed!");
        }));
 
        $("#dashRecTitle").textContent = r.recommendation.title;
        $("#dashRecText").textContent = r.recommendation.text;
    } catch (e) { backendError(e); }
}
pageLoaders.dashboard = loadDashboard;
 
 
/* =========================================
   MAINS EVALUATOR (questions from CSV)
========================================= */
 
const answerInput = $("#answerInput");
const wordCount = $("#wordCount");
const mainsSelect = $("#mainsSelect");
let mainsBank = [];
let currentMains = null;
 
function setMainsQuestion(q) {
    currentMains = q;
    $("#questionText").textContent = q.question;
    $("#questionMeta").textContent = `UPSC ${q.paper} • ${q.subject} • ${q.word_limit} Words • ${q.marks} Marks`;
    mainsSelect.value = q.id;
    answerInput.value = "";
    updateWordCount();
}
 
function updateWordCount() {
    const t = answerInput.value.trim();
    const n = t ? t.split(/\s+/).length : 0;
    const limit = currentMains?.word_limit ?? 150;
    wordCount.textContent = `${n} / ${limit} words`;
    wordCount.style.color = n > limit ? "#c0392b" : "";
}
if (answerInput) {
    answerInput.addEventListener("input", updateWordCount);
}
async function loadMains() {
    if (mainsBank.length) return;


    try {
        mainsBank = await api("/api/mains");
        mainsSelect.innerHTML = mainsBank.map(q =>
            `<option value="${q.id}">${escapeHTML(q.paper)} • ${escapeHTML(q.subject)} — ${escapeHTML(q.question.slice(0, 70))}...</option>`
        ).join("");
        setMainsQuestion(mainsBank[0]);
    } catch (e) { backendError(e); }
}
pageLoaders.evaluator = loadMains;
 
if (mainsSelect) {
    mainsSelect.addEventListener("change", () => {
        const selectedQuestion = mainsBank.find(
            q => q.id === mainsSelect.value
        );

        if (selectedQuestion) {
            setMainsQuestion(selectedQuestion);
        }
    });
}

const mainsRandom = $("#mainsRandom");

if (mainsRandom) {
    mainsRandom.addEventListener("click", () => {
        if (mainsBank.length) {
            setMainsQuestion(
                mainsBank[Math.floor(Math.random() * mainsBank.length)]
            );
        }
    });
}
 
const evaluateBtn = $("#evaluateBtn");
const evaluateBtnHTML = evaluateBtn.innerHTML;
 
evaluateBtn.addEventListener("click", async () => {
    const answer = answerInput.value.trim();
    if (!currentMains) return showToast("Questions are still loading.");
    if (answer.length < 20) {
        showToast("Please write a longer answer first.");
        return answerInput.focus();
    }
 
    evaluateBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Evaluating...';
    evaluateBtn.disabled = true;
    try {
        const data = await post("/api/evaluate", {
            question: currentMains.question, answer,
            word_limit: currentMains.word_limit, marks: currentMains.marks
        });
        renderEvaluation(data);
        showToast("AI evaluation completed.");
    } catch (e) { backendError(e); }
    finally {
        evaluateBtn.innerHTML = evaluateBtnHTML;
        evaluateBtn.disabled = false;
    }
});
 
function renderEvaluation(d) {
    $("#evalResultBody").innerHTML = `
        <div class="result-heading">
            <div class="result-circle"><strong>${d.score}</strong><small>/${d.max_score}</small></div>
            <div>
                <span>AI SCORE</span>
                <h3>${escapeHTML(d.verdict)}</h3>
                <p>${escapeHTML(d.summary)}</p>
            </div>
        </div>
        <div class="criteria">
            ${d.criteria.map(c => `
                <div>
                    <span>${escapeHTML(c.label)}</span>
                    <strong>${c.score}/${c.max_score}</strong>
                    <div class="mini-progress"><i style="width:${Math.round(c.score / c.max_score * 100)}%"></i></div>
                </div>`).join("")}
        </div>
        <div class="feedback-box">
            <h4><i class="fa-solid fa-lightbulb"></i> AI Feedback</h4>
            <ul>${d.feedback.map(f => `<li>${escapeHTML(f)}</li>`).join("")}</ul>
        </div>`;
}
 
 
/* =========================================
   NEWSPAPER ANALYZER
========================================= */
 
const newsFile = $("#newsFile");
const fileName = $("#fileName");
const TAG_CLASSES = ["green-tag", "blue-tag", "orange-tag", "purple-tag"];
let lastNewsFile = null;
 
function renderNewspaper(d) {
    $("#newsItemsList").innerHTML = d.news_items.map((it, i) => `
        <div class="news-item">
            <span class="news-number">${String(i + 1).padStart(2, "0")}</span>
            <div>
                <h4>${escapeHTML(it.title)}</h4>
                <p>${escapeHTML(it.summary)}</p>
                ${(it.tags || []).map((t, k) =>
                    `<span class="tag ${TAG_CLASSES[k % 4]}">${escapeHTML(t)}</span>`).join("")}
            </div>
        </div>`).join("") || '<p class="muted-note">No UPSC-relevant news found.</p>';
 
    $("#generatedQuestionsList").innerHTML = d.questions.map((q, i) => `
        <div class="generated-question"><span>Q${i + 1}</span><p>${escapeHTML(q)}</p></div>`).join("")
        || '<p class="muted-note">No questions generated.</p>';
 
    $("#newsMcqList").innerHTML = (d.mcqs || []).map((m, i) => `
        <div class="mcq-item">
            <p><b>${i + 1}.</b> ${escapeHTML(m.question)}</p>
            <ul>${Object.entries(m.options).map(([k, v]) =>
                `<li class="${k === m.answer ? "correct-opt" : ""}"><b>${k}.</b> ${escapeHTML(v)}</li>`).join("")}</ul>
            <small>Answer: ${escapeHTML(m.answer)}${m.explanation ? " — " + escapeHTML(m.explanation) : ""}</small>
        </div>`).join("") || '<p class="muted-note">No MCQs generated.</p>';
}
 
async function analyzeNewspaper(file) {
    fileName.textContent = "⏳ Analyzing " + file.name + "...";
    const fd = new FormData();
    fd.append("file", file);
    try {
        renderNewspaper(await api("/api/newspaper/analyze", { method: "POST", body: fd }));
        fileName.textContent = "✓ " + file.name + " analyzed";
        showToast("Newspaper analyzed successfully.");
    } catch (e) {
        fileName.textContent = "";
        backendError(e);
    }
}
 

if (newsFile) {
    newsFile.addEventListener("change", () => {
        if (!newsFile.files.length) return;
        lastNewsFile = newsFile.files[0];
        analyzeNewspaper(lastNewsFile);
    });
}

const moreQuestionsBtn = $("#moreQuestions");

if (moreQuestionsBtn) {
    moreQuestionsBtn.addEventListener("click", () => {
        lastNewsFile
            ? analyzeNewspaper(lastNewsFile)
            : showToast("Upload a newspaper first.");
    });
}
 
/* =========================================
   REVISION MAP
========================================= */
 
async function loadRevision() {
    try {
        const r = await api("/api/revision");
        $("#revScore").textContent = r.score + "%";
        $("#revSummary").textContent = r.high_count
            ? `AI has identified ${r.high_count} subject(s) that need immediate revision.`
            : "No subject is in the danger zone. Keep practising to stay sharp.";
        $("#revPriorities").innerHTML = r.items.slice(0, 4).map(i =>
            `<span class="priority ${i.priority}">${escapeHTML(i.subject)} • ${i.priority[0].toUpperCase() + i.priority.slice(1)}</span>`).join("");
 
        $("#revGrid").innerHTML = r.items.map(i => `
            <div class="revision-card ${i.priority === "high" ? "high-priority" : ""}">
                <div class="revision-top"><span class="priority ${i.priority}">${i.priority.toUpperCase()}${i.priority === "high" ? " PRIORITY" : ""}</span></div>
                <h3>${escapeHTML(i.subject)}</h3>
                <p>${i.attempts ? "Weak topics: " : "Start with: "}${i.topics.map(escapeHTML).join(", ")}.</p>
                <div class="revision-progress">
                    <div><span>${i.attempts ? "Accuracy" : "Not attempted yet"}</span><strong>${i.progress}%</strong></div>
                    <div class="progress"><i style="width:${i.progress}%"></i></div>
                </div>
                <button class="btn small primary" data-test="${escapeHTML(i.subject)}">Practice Now</button>
            </div>`).join("");
        $$("#revGrid [data-test]").forEach(b => b.addEventListener("click", () => {
            showPage("tests");
            startTest(b.dataset.test.toLowerCase().replace(/\W+/g, "-").replace(/^-|-$/g, ""));
        }));
 
        $("#revSchedule").innerHTML = r.schedule.map(d => `
            <div class="schedule-day">
                <strong>${d.day}</strong>
                <ul>${d.tasks.map(t => `<li>${escapeHTML(t)}</li>`).join("")}</ul>
            </div>`).join("");
    } catch (e) { backendError(e); }
}
pageLoaders.revision = loadRevision;
$("#regenPlan").addEventListener("click", async () => { await loadRevision(); showToast("Plan refreshed from your latest results."); });
 
 
/* =========================================
   INTERVIEW SIMULATOR
========================================= */
 
const iv = { qs: [], i: 0, answered: false, scores: [], timer: null, sec: 0 };
const ivAnswer = $("#ivAnswer");
const ivNext = $("#ivNext");
 
function ivShow() {
    const q = iv.qs[iv.i];
    $("#ivCategory").textContent = (q.category || "AI INTERVIEWER").toUpperCase();
    $("#ivQuestion").textContent = q.question;
    $("#ivCount").textContent = `${iv.i + 1} / ${iv.qs.length}`;
    ivAnswer.value = "";
    $("#ivFeedback").hidden = true;
    iv.answered = false;
    ivNext.innerHTML = 'Submit Answer <i class="fa-solid fa-arrow-right"></i>';
}
 
async function initInterview(force = false) {
    if (iv.qs.length && !force) return;
    try {
        iv.qs = await api("/api/interview/questions?n=5");
        iv.i = 0; iv.scores = []; iv.sec = 0;
        $("#ivScore").textContent = "-";
        clearInterval(iv.timer);
        iv.timer = setInterval(() => { iv.sec++; $("#ivTime").textContent = fmtTime(iv.sec); }, 1000);
        ivShow();
    } catch (e) { backendError(e); }
}
pageLoaders.interview = () => initInterview();
$("#ivRestart").addEventListener("click", () => initInterview(true));
 
ivNext.addEventListener("click", async () => {
    if (!iv.qs.length) return;
 
    if (iv.answered) {                         // move on
        if (iv.i + 1 < iv.qs.length) { iv.i++; return ivShow(); }
        clearInterval(iv.timer);
        const avg = Math.round(iv.scores.reduce((a, b) => a + b, 0) / iv.scores.length);
        $("#ivFeedback").hidden = false;
        $("#ivFeedback").innerHTML = `<h4>Session complete</h4><p>Average score: <b>${avg}%</b> over ${iv.scores.length} questions.</p>`;
        ivNext.disabled = true;
        return;
    }
 
    const answer = ivAnswer.value.trim();
    if (answer.length < 10) return showToast("Please speak or type a longer answer.");
 
    ivNext.disabled = true;
    try {
        const r = await post("/api/interview/evaluate", { question: iv.qs[iv.i].question, answer });
        iv.scores.push(r.overall);
        iv.answered = true;
        $("#ivScore").textContent = r.overall + "%";
        $("#ivFeedback").hidden = false;
        $("#ivFeedback").innerHTML = `
            <h4>Score: ${r.overall}%</h4>
            <p class="iv-scores">${Object.entries(r.scores).map(([k, v]) => `${k}: <b>${v}/10</b>`).join(" • ")}</p>
            <ul>${r.feedback.map(f => `<li>${escapeHTML(f)}</li>`).join("")}</ul>
            ${r.follow_up ? `<p><i>Follow-up: ${escapeHTML(r.follow_up)}</i></p>` : ""}`;
        ivNext.innerHTML = (iv.i + 1 < iv.qs.length ? "Next Question" : "Finish") + ' <i class="fa-solid fa-arrow-right"></i>';
    } catch (e) { backendError(e); }
    finally { ivNext.disabled = false; }
});
 
/* Microphone -> browser speech recognition (falls back to typing) */
const micButton = $("#micButton");
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null, recording = false;
 
micButton.setAttribute("aria-pressed", "false");
micButton.addEventListener("click", () => {
    if (!SR) return showToast("Speech recognition isn't supported in this browser. Please type your answer.");
    if (!recording) {
        recognizer = new SR();
        recognizer.lang = "en-IN";
        recognizer.continuous = true;
        recognizer.interimResults = false;
        recognizer.onresult = e => {
            for (let k = e.resultIndex; k < e.results.length; k++) {
                if (e.results[k].isFinal) ivAnswer.value += (ivAnswer.value ? " " : "") + e.results[k][0].transcript.trim();
            }
        };
        recognizer.onend = () => { if (recording) micToggle(false); };
        recognizer.onerror = () => micToggle(false);
        recognizer.start();
        micToggle(true);
    } else {
        recognizer.stop();
        micToggle(false);
    }
});
 
function micToggle(on) {
    recording = on;
    micButton.classList.toggle("recording", on);
    micButton.setAttribute("aria-pressed", String(on));
    micButton.innerHTML = `<i class="fa-solid ${on ? "fa-stop" : "fa-microphone"}"></i>`;
    showToast(on ? "Recording started..." : "Recording stopped.");
}
 
 
/* =========================================
   TEST SERIES (MCQs from CSV)
========================================= */
 
const T = { list: [], test: null, qs: [], idx: 0, answers: {}, sec: 0, timer: null };
 
async function loadTests() {
    try {
        T.list = await api("/api/tests");
        renderTestList("all");
    } catch (e) { backendError(e); }
}
pageLoaders.tests = loadTests;
 
function renderTestList(filter) {
    $("#testGrid").innerHTML = T.list.filter(t => filter === "all" || t.type === filter).map(t => `
        <div class="test-card">
            <div class="test-icon"><i class="fa-solid ${t.type === "PRELIMS" ? "fa-landmark" : "fa-book"}"></i></div>
            <span class="tag ${t.type === "PRELIMS" ? "purple-tag" : "green-tag"}">${t.type === "PRELIMS" ? "FULL MOCK" : "SUBJECT"}</span>
            <h3>${escapeHTML(t.title)}</h3>
            <p>${t.count} Questions • ${t.minutes} Minutes</p>
            <div class="test-meta"><span>Difficulty: <b>${t.difficulty}</b></span><span>${t.marks} Marks</span></div>
            <button class="btn primary full" data-start="${t.id}">Start Test</button>
        </div>`).join("");
    $$("#testGrid [data-start]").forEach(b => b.addEventListener("click", () => startTest(b.dataset.start)));
}
 
$$("#testTabs button").forEach(b => b.addEventListener("click", () => {
    $$("#testTabs button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    renderTestList(b.dataset.filter);
}));
 
async function startTest(id) {
    try {
        if (!T.list.length) T.list = await api("/api/tests");
        T.test = T.list.find(t => t.id === id);
        if (!T.test) return showToast("Test not found.");
        T.qs = await api(`/api/tests/${id}/questions`);
        T.idx = 0; T.answers = {}; T.sec = 0;
        T.qs.forEach(q => T.answers[q.id] = "");
        $("#testList").hidden = true;
        $("#testResult").hidden = true;
        $("#testRunner").hidden = false;
        $("#trTitle").textContent = T.test.title;
        clearInterval(T.timer);
        T.timer = setInterval(() => {
            T.sec++;
            const left = T.test.minutes * 60 - T.sec;
            $("#trTimer").textContent = fmtTime(Math.max(0, left));
            if (left <= 0) { showToast("Time's up! Submitting..."); submitTest(); }
        }, 1000);
        $("#trTimer").textContent = fmtTime(T.test.minutes * 60);
        renderQuestion();
    } catch (e) { backendError(e); }
}
 
function renderQuestion() {
    const q = T.qs[T.idx];
    const answered = Object.values(T.answers).filter(Boolean).length;
    $("#trProgress").textContent = `Question ${T.idx + 1} of ${T.qs.length} • ${answered} answered`;
    $("#trBar").style.width = ((T.idx + 1) / T.qs.length * 100) + "%";
    $("#trMeta").textContent = `${q.subject} • ${q.topic} • ${q.difficulty}`;
    $("#trQuestion").textContent = q.question;
    $("#trOptions").innerHTML = Object.entries(q.options).map(([k, v]) => `
        <button class="tr-option ${T.answers[q.id] === k ? "selected" : ""}" data-opt="${k}">
            <b>${k}</b><span>${escapeHTML(v)}</span>
        </button>`).join("");
    $$("#trOptions .tr-option").forEach(b => b.addEventListener("click", () => {
        T.answers[q.id] = b.dataset.opt;
        renderQuestion();
    }));
    $("#trPrev").disabled = T.idx === 0;
    $("#trNext").disabled = T.idx === T.qs.length - 1;
}
 
$("#trPrev").addEventListener("click", () => { T.idx--; renderQuestion(); });
$("#trNext").addEventListener("click", () => { T.idx++; renderQuestion(); });
$("#trClear").addEventListener("click", () => { T.answers[T.qs[T.idx].id] = ""; renderQuestion(); });
$("#trSubmit").addEventListener("click", () => {
    const skipped = Object.values(T.answers).filter(a => !a).length;
    if (skipped && !confirm(`${skipped} question(s) unanswered. Submit anyway?`)) return;
    submitTest();
});
 
async function submitTest() {
    clearInterval(T.timer);
    try {
        const r = await post("/api/tests/submit", { test_id: T.test.id, answers: T.answers, seconds: T.sec });
        $("#testRunner").hidden = true;
        const box = $("#testResult");
        box.hidden = false;
        box.innerHTML = `
            <div class="panel-header"><div><h3>${escapeHTML(T.test.title)} — Result</h3>
                <p>Time taken: ${fmtTime(T.sec)}</p></div></div>
            <div class="result-grid">
                <div><strong>${r.marks}</strong><span>/ ${r.max_marks} marks</span></div>
                <div><strong>${r.correct}</strong><span>Correct</span></div>
                <div><strong>${r.wrong}</strong><span>Wrong</span></div>
                <div><strong>${r.skipped}</strong><span>Skipped</span></div>
                <div><strong>${r.accuracy}%</strong><span>Accuracy</span></div>
            </div>
            <h4 style="margin:22px 0 10px">Answer Review</h4>
            ${r.review.map((q, i) => `
                <div class="review-item ${q.selected ? (q.correct ? "ok" : "bad") : "skip"}">
                    <p><b>${i + 1}.</b> ${escapeHTML(q.question)}</p>
                    <small>Your answer: <b>${q.selected || "—"}</b> • Correct: <b>${q.answer}</b> (${escapeHTML(q.options[q.answer])})</small>
                    <small>${escapeHTML(q.explanation)}</small>
                </div>`).join("")}
            <div style="display:flex;gap:10px;margin-top:18px">
                <button class="btn primary" id="trAgain">Back to Tests</button>
                <button class="btn outline" data-go-result="revision">View Revision Plan</button>
            </div>`;
        $("#trAgain").addEventListener("click", () => {
            box.hidden = true;
            $("#testList").hidden = false;
        });
        $('[data-go-result="revision"]').addEventListener("click", () => showPage("revision"));
    } catch (e) { backendError(e); }
}
 
 
/* =========================================
   ANALYTICS
========================================= */
 
async function loadAnalytics() {
    try {
        const s = await api("/api/stats");
        $("#anAccuracy").textContent = s.accuracy + "%";
        const d = $("#anDelta");
        d.textContent = s.accuracy_delta ? `${s.accuracy_delta > 0 ? "↑" : "↓"} ${Math.abs(s.accuracy_delta)}% vs last week` : `${s.questions_attempted} questions attempted`;
        d.className = s.accuracy_delta > 0 ? "positive" : "";
        $("#anMains").textContent = s.mains_avg_pct + "%";
        $("#anMainsSub").textContent = `${s.interviews_done} interview answers scored`;
        $("#anAnswers").textContent = s.answers_written;
        $("#anAnswersSub").textContent = `${s.answers_this_week} this week`;
        $("#anHours").textContent = s.study_hours_30d + "h";
 
        const step = 560 / 6;
        $("#anLine").setAttribute("points",
            s.weekly.map((w, i) => `${Math.round(20 + i * step)},${Math.round(245 - w.accuracy * 2.2)}`).join(" "));
        $("#anLabels").innerHTML = s.weekly.map(w => `<span>${w.label}</span>`).join("");
 
        $("#anStrength").innerHTML = s.subject_strength.map(x => `
            <div><span>${escapeHTML(x.subject)}</span><strong>${x.accuracy}%</strong></div>
            <div class="progress"><i style="width:${x.accuracy}%"></i></div>`).join("");
    } catch (e) { backendError(e); }
}
pageLoaders.analytics = loadAnalytics;
 
 
/* =========================================
   AI DOUBT SOLVER
========================================= */
 
const chatInput = $("#chatInput");
const chatBody = $("#chatBody");
let chatHistory = [];
 
function addMessage(html, cls = "") {
    const el = document.createElement("div");
    el.className = "message " + cls;
    el.innerHTML = html;
    chatBody.appendChild(el);
    chatBody.scrollTop = chatBody.scrollHeight;
    return el;
}
 
async function sendChat() {
    const text = chatInput.value.trim();
    if (!text) return;
 
    addMessage(`<div><span class="message-name" style="text-align:right;">You</span>
        <p class="user-bubble">${escapeHTML(text)}</p></div>`, "user-message");
    chatInput.value = "";
    chatInput.disabled = true;
 
    const typing = addMessage(`<div class="message-avatar"><i class="fa-solid fa-robot"></i></div>
        <div><span class="message-name">UPSC AI</span><p><i class="fa-solid fa-ellipsis fa-fade"></i></p></div>`);
 
    let reply;
    try {
        reply = (await post("/api/chat", { message: text, history: chatHistory })).reply;
        chatHistory.push({ role: "user", content: text }, { role: "assistant", content: reply });
    } catch (e) {
        reply = `I couldn't reach the AI backend. Make sure it is running at ${API_BASE_URL} (${e.message}).`;
    }
 
    typing.remove();
    addMessage(`<div class="message-avatar"><i class="fa-solid fa-robot"></i></div>
        <div><span class="message-name">UPSC AI</span>
        <p style="white-space:pre-wrap">${escapeHTML(reply)}</p></div>`);
    chatInput.disabled = false;
    chatInput.focus();
}
 
$("#sendMessage").addEventListener("click", sendChat);
chatInput.addEventListener("keydown", e => { if (e.key === "Enter") sendChat(); });
$$(".suggestions button").forEach(b => b.addEventListener("click", () => {
    chatInput.value = b.textContent.trim();
    sendChat();
}));
 
 
/* =========================================
   MISC UI
========================================= */
 
$$(".setting-tab").forEach(b => b.addEventListener("click", () => {
    $$(".setting-tab").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
}));
 
$$(".settings-grid .btn").forEach(b => b.addEventListener("click", () => showToast("Profile settings saved!")));
 
$$(".mentor-card .btn").forEach(b => b.addEventListener("click", () =>
    showToast("Mentor booking will be available in the next release.")));
 
const searchInput = $(".search-box input");
searchInput?.addEventListener("keydown", e => {
    if (e.key === "Enter" && searchInput.value.trim()) {
        showToast("Searching UPSC topics for: " + searchInput.value.trim());
    }
});
 
/* Backend health check */
api("/api/health")
    .then(h => { if (!h.ai) showToast("Backend is running, but AI is unavailable. Check the backend AI configuration."); })
    .catch(() => showToast("Backend not reachable at " + API_BASE_URL));
 
showPage("home");