/* ---------- Dark-mode toggle (persisted) ---------- */
const THEME_KEY = "presphere-theme";

function applyTheme(dark) {
    document.body.classList.toggle("dark-mode", dark);
}

let savedTheme = null;
try { savedTheme = localStorage.getItem(THEME_KEY); } catch { /* storage blocked */ }
applyTheme(savedTheme === "dark");

const headerRight = document.querySelector(".header-right");

if (headerRight && !document.getElementById("themeToggle")) {
    const btn = document.createElement("button");
    btn.id = "themeToggle";
    btn.className = "icon-btn theme-toggle";
    btn.type = "button";
    btn.setAttribute("aria-label", "Toggle dark mode");
    btn.innerHTML = '<i class="fa-solid fa-moon"></i>';
    headerRight.prepend(btn);

    btn.addEventListener("click", () => {
        const dark = !document.body.classList.contains("dark-mode");
        applyTheme(dark);
        try { localStorage.setItem(THEME_KEY, dark ? "dark" : "light"); } catch { /* ignore */ }
    });
}


/* ---------- Dashboard: total questions + total score card ---------- */
// Uses globals defined in script.js: api, $, $$, showToast, showPage, pageLoaders, escapeHTML, API_BASE_URL

async function loadScoreCard() {
    try {
        const s = await api("/api/score-summary");
        $("#dsQuestions").textContent = s.total_questions;
        $("#dsMarks").textContent = s.total_marks;
        $("#dsMax").textContent = `of ${s.max_marks} marks`;
    } catch { /* dashboard loader already reports backend errors */ }
}

const baseDashboardLoader = pageLoaders.dashboard;
pageLoaders.dashboard = () => { baseDashboardLoader?.(); loadScoreCard(); };


/* ---------- My Score page ---------- */

async function loadScore() {
    try {
        const s = await api("/api/score-summary");
        $("#scQuestions").textContent = s.total_questions;
        $("#scTests").textContent = `${s.tests_taken} test${s.tests_taken === 1 ? "" : "s"} taken`;
        $("#scMarks").textContent = s.total_marks;
        $("#scMax").textContent = `of ${s.max_marks} marks`;
        $("#scCW").textContent = `${s.correct} / ${s.wrong}`;
        $("#scAcc").textContent = s.accuracy + "%";

        $("#scSubjects").innerHTML = s.subjects.length ? s.subjects.map(x => `
            <div class="sc-subject">
                <button class="sc-row" aria-expanded="false">
                    <span class="sc-name">${escapeHTML(x.subject)}</span>
                    <span class="sc-meta">${x.attempted} Qs • ${x.correct} correct • ${x.wrong} wrong</span>
                    <strong>${x.marks} / ${x.max_marks}</strong>
                    <i class="fa-solid fa-chevron-down"></i>
                </button>
                <div class="progress"><i style="width:${x.accuracy}%"></i></div>
                <div class="sc-topics" hidden>
                    ${x.topics.map(t => `
                        <div>
                            <span>${escapeHTML(t.topic)}</span>
                            <span>${t.attempted} Qs • ${t.correct}✓ ${t.wrong}✗</span>
                            <b>${t.marks} / ${t.max_marks}</b>
                        </div>`).join("")}
                </div>
            </div>`).join("")
            : '<p class="muted-note">No test submitted yet. Take a test to see your subject-wise marks.</p>';

        $$("#scSubjects .sc-row").forEach(row => row.addEventListener("click", () => {
            const open = row.getAttribute("aria-expanded") === "true";
            row.setAttribute("aria-expanded", String(!open));
            row.parentElement.querySelector(".sc-topics").hidden = open;
        }));

        $("#scTestsList").innerHTML = s.recent_tests.length ? s.recent_tests.map(t => `
            <div class="sc-test">
                <div>${escapeHTML(t.title)}<small>${escapeHTML(t.date)}</small></div>
                <span>${t.accuracy}% accuracy</span>
                <strong>${t.score} / ${t.total}</strong>
            </div>`).join("")
            : '<p class="muted-note">No tests yet.</p>';
    } catch (e) { backendError(e); }
}
pageLoaders.score = loadScore;

// Clicking "Total Score" jumps to the subject-wise breakdown
$("#scTotalCard")?.addEventListener("click", () => {
    $("#scSubjectsPanel")?.scrollIntoView({ behavior: "smooth", block: "start" });
    $$("#scSubjects .sc-row").forEach(r => {
        r.setAttribute("aria-expanded", "true");
        r.parentElement.querySelector(".sc-topics").hidden = false;
    });
});


/* ---------- Video lectures ---------- */

async function loadVideos() {
    try {
        const [list, tests] = await Promise.all([api("/api/videos"), api("/api/tests")]);

        const subjects = [...new Set(tests.filter(t => t.type === "SUBJECT").map(t => t.subject))];
        $("#vidSubjects").innerHTML = subjects.map(s => `<option value="${escapeHTML(s)}">`).join("");

        $("#vidGrid").innerHTML = list.length ? list.map(v => `
            <div class="video-card">
                <video controls preload="metadata" src="${API_BASE_URL + v.url}"></video>
                <div class="video-info">
                    <h4>${escapeHTML(v.title)}</h4>
                    <span class="tag green-tag">${escapeHTML(v.subject)}</span>
                    <small>${v.size_mb} MB • ${escapeHTML(v.date)}</small>
                    <button class="btn small outline" data-del="${v.id}">
                        <i class="fa-solid fa-trash"></i> Delete
                    </button>
                </div>
            </div>`).join("")
            : '<p class="muted-note">No videos uploaded yet.</p>';

        $$("#vidGrid [data-del]").forEach(b => b.addEventListener("click", async () => {
            if (!confirm("Delete this video?")) return;
            try {
                await api("/api/videos/" + b.dataset.del, { method: "DELETE" });
                showToast("Video deleted.");
                loadVideos();
            } catch (e) { backendError(e); }
        }));
    } catch (e) { backendError(e); }
}
pageLoaders.videos = loadVideos;

const vidUploadBtn = $("#vidUpload");

vidUploadBtn?.addEventListener("click", () => {
    const file = $("#vidFile").files[0];
    if (!file) return showToast("Choose a video file first.");

    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", $("#vidTitle").value.trim() || file.name);
    fd.append("subject", $("#vidSubject").value.trim() || "General");

    const bar = $("#vidBar"), wrap = $("#vidProgress"), pct = $("#vidPct");
    wrap.hidden = false;
    pct.hidden = false;
    bar.style.width = "0%";
    pct.textContent = "Uploading… 0%";
    vidUploadBtn.disabled = true;

    const done = () => {
        vidUploadBtn.disabled = false;
        setTimeout(() => { wrap.hidden = true; pct.hidden = true; }, 1200);
    };

    const xhr = new XMLHttpRequest();
    xhr.open("POST", API_BASE_URL + "/api/videos/upload");
    xhr.upload.onprogress = e => {
        if (!e.lengthComputable) return;
        const p = Math.round(e.loaded / e.total * 100);
        bar.style.width = p + "%";
        pct.textContent = `Uploading… ${p}%`;
    };
    xhr.onload = () => {
        done();
        if (xhr.status >= 200 && xhr.status < 300) {
            showToast("Video uploaded successfully.");
            $("#vidFile").value = "";
            $("#vidTitle").value = "";
            loadVideos();
        } else {
            let msg = xhr.status;
            try { msg = JSON.parse(xhr.responseText).detail || msg; } catch { /* not JSON */ }
            showToast("Upload failed: " + msg);
        }
    };
    xhr.onerror = () => { done(); showToast("Upload failed: backend not reachable."); };
    xhr.send(fd);
});

/* ---------- Notes (subject-wise) ---------- */
/* ---------- Notes (subject-wise) ---------- */
/* ---------- Notes (subject-wise) ---------- */

let noteSubject = "all";

const IMG_EXT = [".png", ".jpg", ".jpeg"];

function noteFileButton(n) {
    if (!n.url) return "";
    const href = API_BASE_URL + n.url;
    if (n.ext === ".pdf" || IMG_EXT.includes(n.ext))
        return `<a class="btn small primary" href="${href}" target="_blank" rel="noopener">
                    <i class="fa-solid fa-up-right-from-square"></i> ${n.ext === ".pdf" ? "Open PDF" : "View"}</a>`;
    return `<a class="btn small primary" href="${href}" download>
                <i class="fa-solid fa-download"></i> Download</a>`;
}

async function loadNotes() {
    try {
        const [subs, list] = await Promise.all([
            api("/api/notes/subjects"),
            api("/api/notes?subject=" + encodeURIComponent(noteSubject))
        ]);

        $("#noteSubjects").innerHTML = subs.subjects.map(s => `<option value="${escapeHTML(s.subject)}">`).join("");

        const chips = [{ subject: "all", label: "All", count: subs.total }]
            .concat(subs.subjects.map(s => ({ subject: s.subject, label: s.subject, count: s.count })));

        $("#noteChips").innerHTML = chips.map(c => `
            <button class="note-chip ${c.subject.toLowerCase() === noteSubject.toLowerCase() ? "active" : ""}"
                    data-subject="${encodeURIComponent(c.subject)}">
                ${escapeHTML(c.label)}<span>${c.count}</span>
            </button>`).join("");

        $$("#noteChips .note-chip").forEach(b => b.addEventListener("click", () => {
            noteSubject = decodeURIComponent(b.dataset.subject);
            loadNotes();
        }));

        $("#noteHeading").textContent = (noteSubject === "all" ? "All" : noteSubject) + ` Notes (${list.length})`;

        $("#noteGrid").innerHTML = list.length ? list.map(n => `
            <div class="note-card">
                <div>
                    <h4>${escapeHTML(n.title)}</h4>
                    <span class="tag green-tag">${escapeHTML(n.subject)}</span>
                </div>
                ${n.content ? `<p class="note-excerpt">${escapeHTML(n.content.slice(0, 140))}${n.content.length > 140 ? "…" : ""}</p>
                               <div class="note-body" hidden>${escapeHTML(n.content)}</div>` : ""}
                <small>${n.file_name ? escapeHTML(n.file_name) + " • " + n.size_mb + " MB • " : ""}${escapeHTML(n.date)}</small>
                <div class="note-actions">
                    ${n.content ? `<button class="btn small outline" data-read="1"><i class="fa-solid fa-book-open"></i> Read</button>` : ""}
                    ${noteFileButton(n)}
                    <button class="btn small outline" data-del="${n.id}"><i class="fa-solid fa-trash"></i></button>
                </div>
            </div>`).join("")
            : `<p class="muted-note">No notes${noteSubject === "all" ? "" : " for " + escapeHTML(noteSubject)} yet. Add one below.</p>`;

        $$("#noteGrid [data-read]").forEach(b => b.addEventListener("click", () => {
            const body = b.closest(".note-card").querySelector(".note-body");
            const excerpt = b.closest(".note-card").querySelector(".note-excerpt");
            body.hidden = !body.hidden;
            excerpt.hidden = !body.hidden;
            b.innerHTML = body.hidden
                ? '<i class="fa-solid fa-book-open"></i> Read'
                : '<i class="fa-solid fa-xmark"></i> Close';
        }));

        $$("#noteGrid [data-del]").forEach(b => b.addEventListener("click", async () => {
            if (!confirm("Delete this note?")) return;
            try {
                await api("/api/notes/" + b.dataset.del, { method: "DELETE" });
                showToast("Note deleted.");
                loadNotes();
            } catch (e) { backendError(e); }
        }));

        // pre-fill the add form with the currently selected subject
        const subjInput = $("#noteSubject");
        if (subjInput && !subjInput.value && noteSubject !== "all") subjInput.value = noteSubject;
    } catch (e) { backendError(e); }
}
pageLoaders.notes = loadNotes;

$("#noteSave")?.addEventListener("click", async () => {
    const content = $("#noteContent").value.trim();
    const file = $("#noteFile").files[0];
    const subject = $("#noteSubject").value.trim();

    if (!subject) return showToast("Enter a subject (e.g. Polity).");
    if (!content && !file) return showToast("Write some notes or attach a file.");

    const fd = new FormData();
    fd.append("title", $("#noteTitle").value.trim());
    fd.append("subject", subject);
    fd.append("content", content);
    if (file) fd.append("file", file);

    const btn = $("#noteSave");
    btn.disabled = true;
    try {
        await api("/api/notes", { method: "POST", body: fd });
        showToast("Note saved.");
        $("#noteTitle").value = "";
        $("#noteContent").value = "";
        $("#noteFile").value = "";
        noteSubject = subject;          // jump to the subject the note was saved under
        loadNotes();
    } catch (e) { backendError(e); }
    finally { btn.disabled = false; }
});



/* ---------- Login / sign up + roles ---------- */

function showAuth() {
    const ov = document.createElement("div");
    ov.id = "authOverlay";
    ov.innerHTML = `
        <div class="auth-card">
            <h2>PreSphere<span>AI</span></h2>
            <p class="auth-sub">Log in to start studying</p>
            <div class="auth-tabs">
                <button class="active" data-mode="login" type="button">Login</button>
                <button data-mode="register" type="button">Sign up</button>
            </div>
            <input id="authUser" type="text" placeholder="Username" autocomplete="username">
            <input id="authPass" type="password" placeholder="Password (min 6 characters)" autocomplete="current-password">
            <p id="authErr" class="auth-err"></p>
            <button class="btn primary full" id="authGo" type="button">Login</button>
        </div>`;
    document.body.appendChild(ov);

    let mode = "login";
    const err = $("#authErr", ov), go = $("#authGo", ov);

    $$(".auth-tabs button", ov).forEach(b => b.addEventListener("click", () => {
        mode = b.dataset.mode;
        $$(".auth-tabs button", ov).forEach(x => x.classList.toggle("active", x === b));
        go.textContent = mode === "login" ? "Login" : "Create account";
        $("#authPass", ov).autocomplete = mode === "login" ? "current-password" : "new-password";
        err.textContent = "";
    }));

    async function submit() {
        const username = $("#authUser", ov).value.trim();
        const password = $("#authPass", ov).value;
        if (!username || !password) { err.textContent = "Enter username and password."; return; }
        go.disabled = true;
        err.textContent = "";
        try {
            await post("/api/auth/" + mode, { username, password });
            location.reload();
        } catch (e) {
            err.textContent = e.message;
            go.disabled = false;
        }
    }

    go.addEventListener("click", submit);
    ov.addEventListener("keydown", e => { if (e.key === "Enter") submit(); });
    $("#authUser", ov).focus();
}

function applyUser(user) {
    document.body.classList.add(user.role === "admin" ? "role-admin" : "role-student");
    $$(".user-mini strong, .profile-info strong").forEach(el => el.textContent = user.username);
    $$(".user-mini small, .profile-info small").forEach(el => el.textContent = user.role === "admin" ? "Admin" : "Student");

    // edit-only panels (server also blocks students with 403)
    $(".video-upload")?.classList.add("admin-only");
    $("#noteSave")?.closest(".panel")?.classList.add("admin-only");

    const out = document.createElement("button");
    out.id = "logoutBtn";
    out.className = "btn small outline";
    out.type = "button";
    out.textContent = "Logout";
    $(".header-right")?.append(out);
    out.addEventListener("click", async () => {
        try { await post("/api/auth/logout", {}); } catch { /* ignore */ }
        location.reload();
    });
}

(async () => {
    let user = null;
    try { user = (await api("/api/auth/me")).user; } catch { /* backend unreachable */ }
    user ? applyUser(user) : showAuth();
})();