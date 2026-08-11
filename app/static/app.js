/* MovieFit Studio 프론트엔드
 *
 * 원칙 (TECH_SPEC 9절): 화면의 모든 내용은 `project` 객체 하나에서 나온다.
 * 이 객체가 바뀌면 화면을 다시 그리고, 2초 뒤 서버에 자동 저장한다.
 */

"use strict";

// ══ 전역 상태 ══════════════════════════════════════════════
let project = null;        // 현재 열려 있는 프로젝트
let saveTimer = null;      // 자동 저장 디바운스
let selectedId = null;     // 선택된 자막 id
let voices = [];           // 서버에서 받아 온 목소리 목록
let presets = { builtin: [], user: [] };
let pxPerSec = 40;         // 타임라인 확대 배율
let undoStack = [];
let redoStack = [];
const UNDO_MAX = 50;

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ══ 서버 통신 ══════════════════════════════════════════════
async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) {
    let message = `서버 오류 (${res.status})`;
    try { const body = await res.json(); if (body.detail) message = body.detail; } catch (_) {}
    throw new Error(message);
  }
  return res.status === 204 ? null : res.json();
}

// ══ 알림 ═══════════════════════════════════════════════════
let toastTimer = null;
function toast(message, { error = false, undo = null } = {}) {
  const el = $("#toast");
  el.innerHTML = "";
  el.append(document.createTextNode(message));
  el.classList.toggle("is-error", error);

  if (undo) {
    const btn = document.createElement("button");
    btn.className = "t-undo";
    btn.textContent = "되돌리기";
    btn.addEventListener("click", () => { undo(); el.hidden = true; });
    el.appendChild(btn);
  }
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, error ? 7000 : undo ? 6000 : 3000);
}

// ══ 시간 표시 ══════════════════════════════════════════════
function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const d = Math.floor((sec * 10) % 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${d}`;
}
function parseTime(text) {
  // "01:23.4" 또는 "83.4" 둘 다 받는다
  const t = String(text).trim();
  const m = t.match(/^(\d+):(\d{1,2})(?:\.(\d))?$/);
  if (m) return (+m[1]) * 60 + (+m[2]) + (m[3] ? +m[3] / 10 : 0);
  const n = parseFloat(t);
  return isNaN(n) ? null : n;
}

// ══ 되돌리기 ═══════════════════════════════════════════════
function snapshot() {
  if (!project) return;
  undoStack.push(JSON.stringify({ segments: project.segments, style: project.style }));
  if (undoStack.length > UNDO_MAX) undoStack.shift();
  redoStack = [];
  refreshUndoButtons();
}
function restore(json) {
  const data = JSON.parse(json);
  project.segments = data.segments;
  project.style = data.style;
  renderAll();
  markDirty();
}
function undo() {
  if (!undoStack.length) return;
  redoStack.push(JSON.stringify({ segments: project.segments, style: project.style }));
  restore(undoStack.pop());
  refreshUndoButtons();
  toast("되돌렸습니다.");
}
function redo() {
  if (!redoStack.length) return;
  undoStack.push(JSON.stringify({ segments: project.segments, style: project.style }));
  restore(redoStack.pop());
  refreshUndoButtons();
}
function refreshUndoButtons() {
  $("#btn-undo").disabled = undoStack.length === 0;
  $("#btn-redo").disabled = redoStack.length === 0;
}

// ══ 자동 저장 ══════════════════════════════════════════════
function markDirty() {
  if (!project) return;
  const state = $("#save-state");
  state.textContent = "저장 중…";
  state.classList.add("is-saving");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 2000);
}
async function saveNow() {
  if (!project) return;
  const state = $("#save-state");
  try {
    const saved = await api(`/api/projects/${encodeURIComponent(project.id)}`, {
      method: "PUT", body: JSON.stringify(project),
    });
    project.updated_at = saved.updated_at;
    state.textContent = "저장됨";
    saveTimer = null;
  } catch (err) {
    state.textContent = "저장 실패";
    toast(`저장하지 못했습니다: ${err.message}`, { error: true });
  } finally {
    state.classList.remove("is-saving");
  }
}

// ══ 화면 전환 ══════════════════════════════════════════════
function showStart() {
  project = null; selectedId = null; undoStack = []; redoStack = [];
  $("#view-editor").hidden = true;
  $("#view-start").hidden = false;
  const p = $("#player"); p.removeAttribute("src"); p.load();
  loadRecent();
  history.replaceState(null, "", "/");
}
function showEditor() {
  $("#view-start").hidden = true;
  $("#view-editor").hidden = false;
}

// ══ 최근 프로젝트 ══════════════════════════════════════════
async function loadRecent() {
  const list = $("#recent-list");
  try {
    const { projects } = await api("/api/projects");
    if (!projects.length) {
      list.innerHTML = '<li class="empty">아직 만든 프로젝트가 없습니다.</li>';
      return;
    }
    list.innerHTML = "";
    for (const p of projects) {
      const li = document.createElement("li");
      li.className = "recent-item";
      li.tabIndex = 0;

      const name = document.createElement("span");
      name.className = "r-name";
      name.textContent = p.name;

      const meta = document.createElement("span");
      meta.className = "r-meta";
      meta.textContent = `${p.mode === "script" ? "대본" : "영상"} · 자막 ${p.segment_count}개 · ${p.updated_at}`;

      const del = document.createElement("button");
      del.className = "r-del"; del.title = "이 프로젝트 삭제"; del.textContent = "✕";
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`'${p.name}' 프로젝트를 삭제할까요?\n되돌릴 수 없습니다.`)) return;
        try {
          await api(`/api/projects/${encodeURIComponent(p.id)}`, { method: "DELETE" });
          toast("프로젝트를 삭제했습니다."); loadRecent();
        } catch (err) { toast(err.message, { error: true }); }
      });

      const open = () => openProject(p.id);
      li.addEventListener("click", open);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      li.append(name, meta, del);
      list.appendChild(li);
    }
  } catch (err) {
    list.innerHTML = `<li class="empty">목록을 불러오지 못했습니다: ${err.message}</li>`;
  }
}

// ══ 프로젝트 열기 / 만들기 ═════════════════════════════════
async function openProject(id) {
  try { project = await api(`/api/projects/${encodeURIComponent(id)}`); }
  catch (err) { toast(err.message, { error: true }); return; }
  undoStack = []; redoStack = []; selectedId = null;
  renderProject(); showEditor();
  history.replaceState(null, "", `/?project=${encodeURIComponent(id)}`);
  maybeShowCoach();
}
async function createProject({ name, video_path, mode }) {
  try {
    project = await api("/api/projects", { method: "POST", body: JSON.stringify({ name, video_path, mode }) });
  } catch (err) { toast(err.message, { error: true }); return; }
  undoStack = []; redoStack = []; selectedId = null;
  renderProject(); showEditor();
  history.replaceState(null, "", `/?project=${encodeURIComponent(project.id)}`);
  toast("새 프로젝트를 만들었습니다.");
  maybeShowCoach();
}

// ══ 전체 렌더 ══════════════════════════════════════════════
function renderProject() {
  if (!project) return;
  $("#project-name").value = project.name;
  $("#save-state").textContent = "저장됨";
  setMode(project.mode, false);

  const player = $("#player");
  if (project.video_path) {
    player.src = `/media/project/${encodeURIComponent(project.id)}/video`;
    player.hidden = false; player.controls = true;
    $("#no-video").hidden = true;
    $("#file-info").textContent = project.video_path;
  } else {
    player.removeAttribute("src"); player.hidden = true;
    $("#no-video").hidden = false;
    $("#file-info").textContent = "파일 없음 (대본 모드)";
  }

  $("#script-input").value = project.script || "";
  updateScriptStats();
  $("#stt-language").value = project.stt?.language ?? "ko";
  $("#stt-model").value = project.stt?.model ?? "small";

  renderStylePanel();
  renderNarrationPanel();
  renderAll();
  refreshUndoButtons();
}

function renderAll() {
  renderSegments();
  renderTimeline();
  applyOverlayStyle();
  updateOverlay($("#player").currentTime || 0);
}

function setMode(mode, dirty = true) {
  if (!project) return;
  project.mode = mode;
  $("#mode-video").classList.toggle("is-active", mode === "video");
  $("#mode-script").classList.toggle("is-active", mode === "script");
  $("#left-video").hidden = mode !== "video";
  $("#left-script").hidden = mode !== "script";
  if (dirty) markDirty();
}

// ══ 자막 계산 도우미 ═══════════════════════════════════════
function segments() { return project?.segments ?? []; }
function sortSegments() { project.segments.sort((a, b) => a.start - b.start); }
function nextSegId() {
  let max = 0;
  for (const s of segments()) {
    const n = parseInt(String(s.id).replace(/\D/g, ""), 10);
    if (!isNaN(n) && n > max) max = n;
  }
  return "s" + String(max + 1).padStart(3, "0");
}
function segIndex(id) { return segments().findIndex((s) => s.id === id); }

/** 초당 글자수 — 너무 빠르면 못 읽는다. 한국어는 대략 9자/초가 상한. */
function cps(seg) {
  const dur = Math.max(0.1, seg.end - seg.start);
  return (seg.text || "").replace(/\s/g, "").length / dur;
}
function totalDuration() {
  const p = $("#player");
  if (p && isFinite(p.duration) && p.duration > 0) return p.duration;
  const segs = segments();
  return segs.length ? Math.max(...segs.map((s) => s.end)) + 2 : 30;
}

// ══ 자막 목록 렌더 ═════════════════════════════════════════
function renderSegments(filter = "") {
  const list = $("#seg-list");
  const segs = segments();
  $("#seg-count").textContent = `${segs.length}개`;
  list.innerHTML = "";

  if (!segs.length) {
    const li = document.createElement("li");
    li.className = "seg-empty";
    li.innerHTML = `
      <h4>아직 자막이 없습니다</h4>
      <ol>
        <li>왼쪽 <b>[자막 자동 생성]</b>을 누르면 영상에서 말을 알아듣고 자막을 만듭니다.</li>
        <li>또는 위의 <b>[＋ 자막 추가]</b>로 직접 한 줄씩 넣을 수 있습니다.</li>
        <li>대본이 있다면 상단 <b>[대본 모드]</b>에서 나레이션과 자막을 한 번에 만듭니다.</li>
      </ol>`;
    list.appendChild(li);
    return;
  }

  const needle = filter.trim().toLowerCase();
  for (let i = 0; i < segs.length; i++) {
    const seg = segs[i];
    if (needle && !(seg.text || "").toLowerCase().includes(needle)) continue;
    list.appendChild(buildSegmentRow(seg, i));
  }
}

function buildSegmentRow(seg, index) {
  const li = document.createElement("li");
  li.className = "seg-item";
  li.dataset.id = seg.id;
  if (seg.id === selectedId) li.classList.add("is-active");

  // 번호
  const no = document.createElement("span");
  no.className = "seg-no";
  no.textContent = index + 1;

  // 시간 (넛지 버튼 + 직접 입력)
  const times = document.createElement("div");
  times.className = "seg-times";
  times.append(
    nudgeButton(seg, "start", -0.1, "◀"),
    timeInput(seg, "start"),
    nudgeButton(seg, "start", +0.1, "▶"),
    Object.assign(document.createElement("span"), { className: "time-arrow", textContent: "→" }),
    nudgeButton(seg, "end", -0.1, "◀"),
    timeInput(seg, "end"),
    nudgeButton(seg, "end", +0.1, "▶"),
  );

  // 글자 (클릭하면 바로 수정)
  const text = document.createElement("textarea");
  text.className = "seg-text";
  text.rows = 1;
  text.value = seg.text || "";
  text.placeholder = "자막 내용을 입력하세요";
  autoGrow(text);
  text.addEventListener("focus", () => { selectSegment(seg.id, false); setHelp("edit"); });
  text.addEventListener("input", () => {
    seg.text = text.value; autoGrow(text);
    updateRowMeta(li, seg); updateOverlay($("#player").currentTime); markDirty();
  });
  text.addEventListener("change", () => snapshot());
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.ctrlKey) { e.preventDefault(); splitSegment(seg.id, text.selectionStart); }
    else if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); text.blur(); }
    else if (e.key === "Escape") { text.value = seg.text; text.blur(); }
  });

  // 읽기 속도 표시
  const meta = document.createElement("div");
  meta.className = "seg-meta";

  // 동작 버튼 (아이콘 + 글자 병기 — 아이콘만 두면 못 알아본다)
  const actions = document.createElement("div");
  actions.className = "seg-actions";

  const btnSplit = mkBtn("나누기", "글 중간에 커서를 두고 누르면 두 개로 쪼개집니다 (Ctrl+Enter)", () => {
    splitSegment(seg.id, text.selectionStart || Math.floor((seg.text || "").length / 2));
  });
  const btnMerge = mkBtn("합치기", "다음 자막과 하나로 붙입니다", () => mergeSegment(seg.id));
  const btnDel = mkBtn("삭제", "이 자막을 지웁니다 (되돌릴 수 있습니다)", () => deleteSegment(seg.id));
  btnDel.classList.add("btn-del");
  actions.append(btnSplit, btnMerge, btnDel);

  li.addEventListener("click", (e) => {
    if (e.target.closest("button") || e.target.closest("input") || e.target.closest("textarea")) return;
    selectSegment(seg.id, true);
  });

  li.append(no, times, text, meta, actions);
  updateRowMeta(li, seg);
  return li;
}

function mkBtn(label, title, onClick) {
  const b = document.createElement("button");
  b.className = "btn"; b.textContent = label; b.title = title;
  b.addEventListener("click", onClick);
  return b;
}

function nudgeButton(seg, key, delta, glyph) {
  const b = document.createElement("button");
  b.className = "nudge";
  b.textContent = glyph;
  b.title = `${key === "start" ? "시작" : "끝"} 시간을 ${delta > 0 ? "뒤로" : "앞으로"} 0.1초`;
  b.addEventListener("click", () => nudge(seg.id, key, delta));
  return b;
}

function timeInput(seg, key) {
  const input = document.createElement("input");
  input.className = "time-input";
  input.value = fmtTime(seg[key]);
  input.title = "클릭해서 직접 입력할 수 있습니다 (예: 01:23.4)";
  input.addEventListener("focus", () => setHelp("time"));
  input.addEventListener("change", () => {
    const value = parseTime(input.value);
    if (value === null) { input.value = fmtTime(seg[key]); toast("시간 형식이 올바르지 않습니다. 예: 01:23.4", { error: true }); return; }
    snapshot();
    seg[key] = Math.max(0, value);
    if (seg.end <= seg.start) seg.end = seg.start + 0.3;
    sortSegments(); renderAll(); markDirty();
  });
  return input;
}

function autoGrow(el) { el.style.height = "auto"; el.style.height = Math.min(90, el.scrollHeight) + "px"; }

function updateRowMeta(li, seg) {
  const meta = li.querySelector(".seg-meta");
  if (!meta) return;
  const dur = Math.max(0, seg.end - seg.start);
  const speed = cps(seg);
  const cls = speed > 11 ? "is-toofast" : speed > 8.5 ? "is-fast" : "";
  const title = cls ? "읽기에 너무 빠릅니다. 시간을 늘리거나 글을 줄여 보세요." : "읽기 속도(초당 글자수)";
  meta.innerHTML = `<div>${dur.toFixed(1)}초</div><div class="cps ${cls}" title="${title}">${speed.toFixed(1)}자/초</div>`;
}

// ══ 자막 편집 동작 ═════════════════════════════════════════
function selectSegment(id, seek) {
  selectedId = id;
  $$(".seg-item").forEach((el) => el.classList.toggle("is-active", el.dataset.id === id));
  $$(".tl-clip").forEach((el) => el.classList.toggle("is-active", el.dataset.id === id));
  const seg = segments()[segIndex(id)];
  if (seek && seg) {
    const p = $("#player");
    if (p.src) p.currentTime = seg.start + 0.01;
  }
  setHelp("selected");
}

function nudge(id, key, delta) {
  const seg = segments()[segIndex(id)];
  if (!seg) return;
  snapshot();
  seg[key] = Math.max(0, Math.round((seg[key] + delta) * 10) / 10);
  if (seg.end <= seg.start) {
    if (key === "start") seg.start = Math.max(0, seg.end - 0.1);
    else seg.end = seg.start + 0.1;
  }
  sortSegments(); renderAll(); markDirty();
}

function addSegment() {
  snapshot();
  const p = $("#player");
  const start = p.src && isFinite(p.currentTime) ? p.currentTime : (segments().length ? Math.max(...segments().map((s) => s.end)) : 0);
  const seg = { id: nextSegId(), start: Math.round(start * 10) / 10, end: Math.round((start + 2) * 10) / 10, text: "" };
  project.segments.push(seg);
  sortSegments(); renderAll(); markDirty();
  selectSegment(seg.id, false);
  const row = $(`.seg-item[data-id="${seg.id}"] .seg-text`);
  if (row) row.focus();
  toast("자막을 추가했습니다. 내용을 입력하세요.");
}

function deleteSegment(id) {
  const i = segIndex(id);
  if (i < 0) return;
  const before = JSON.stringify(project.segments);
  snapshot();
  const removed = project.segments.splice(i, 1)[0];
  renderAll(); markDirty();
  toast(`자막을 지웠습니다: "${(removed.text || "").slice(0, 16)}"`, {
    undo: () => { project.segments = JSON.parse(before); renderAll(); markDirty(); },
  });
}

/** 글자 커서 위치를 기준으로 두 개로 쪼갠다. 시간은 글자수 비율로 나눈다. */
function splitSegment(id, cursor) {
  const i = segIndex(id);
  if (i < 0) return;
  const seg = project.segments[i];
  const text = seg.text || "";
  const at = clamp(cursor ?? Math.floor(text.length / 2), 1, Math.max(1, text.length - 1));
  if (text.length < 2) { toast("나누기에는 글자가 두 자 이상 필요합니다.", { error: true }); return; }

  snapshot();
  const ratio = at / text.length;
  const mid = seg.start + (seg.end - seg.start) * ratio;

  const second = {
    id: nextSegId(),
    start: Math.round(mid * 10) / 10,
    end: seg.end,
    text: text.slice(at).trim(),
  };
  seg.end = Math.round(mid * 10) / 10;
  seg.text = text.slice(0, at).trim();

  project.segments.splice(i + 1, 0, second);
  sortSegments(); renderAll(); markDirty();
  toast("자막을 두 개로 나눴습니다.");
}

function mergeSegment(id) {
  const i = segIndex(id);
  if (i < 0 || i >= project.segments.length - 1) { toast("마지막 자막은 합칠 대상이 없습니다.", { error: true }); return; }
  snapshot();
  const a = project.segments[i];
  const b = project.segments[i + 1];
  a.text = `${(a.text || "").trim()} ${(b.text || "").trim()}`.trim();
  a.end = b.end;
  project.segments.splice(i + 1, 1);
  renderAll(); markDirty();
  toast("다음 자막과 합쳤습니다.");
}

function shiftAll() {
  const answer = prompt("자막 전체를 몇 초 밀까요?\n뒤로 밀려면 0.5, 앞으로 당기려면 -0.5 처럼 입력하세요.", "0.5");
  if (answer === null) return;
  const delta = parseFloat(answer);
  if (isNaN(delta)) { toast("숫자를 입력해 주세요.", { error: true }); return; }
  snapshot();
  for (const seg of project.segments) {
    seg.start = Math.max(0, Math.round((seg.start + delta) * 10) / 10);
    seg.end = Math.max(0.1, Math.round((seg.end + delta) * 10) / 10);
  }
  sortSegments(); renderAll(); markDirty();
  toast(`전체 자막을 ${delta > 0 ? "+" : ""}${delta}초 옮겼습니다.`);
}

/** 자막 검사 — 겹침, 너무 빠름, 너무 짧음, 빈 자막을 찾아 알려준다. */
function checkSegments() {
  const segs = segments();
  if (!segs.length) { toast("검사할 자막이 없습니다."); return; }

  const problems = [];
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    const n = i + 1;
    if (!(s.text || "").trim()) problems.push(`${n}번: 내용이 비어 있습니다`);
    if (s.end - s.start < 0.3) problems.push(`${n}번: 너무 짧습니다 (${(s.end - s.start).toFixed(1)}초)`);
    if (cps(s) > 11) problems.push(`${n}번: 읽기에 너무 빠릅니다 (${cps(s).toFixed(1)}자/초)`);
    if ((s.text || "").length > (project.style?.max_chars ?? 20) * (project.style?.max_lines ?? 2))
      problems.push(`${n}번: 글자가 너무 많습니다 (${s.text.length}자)`);
    if (i < segs.length - 1 && s.end > segs[i + 1].start + 0.001)
      problems.push(`${n}번과 ${n + 1}번의 시간이 겹칩니다`);
  }

  if (!problems.length) { toast("검사 완료 — 문제가 없습니다."); return; }
  alert(`자막 검사 결과 — ${problems.length}건\n\n` + problems.slice(0, 25).join("\n") +
        (problems.length > 25 ? `\n… 외 ${problems.length - 25}건` : ""));
}

function replaceAll() {
  const from = $("#seg-search").value;
  const to = $("#seg-replace").value;
  if (!from) { toast("바꿀 말을 검색 칸에 입력해 주세요.", { error: true }); return; }
  let count = 0;
  snapshot();
  for (const seg of project.segments) {
    if ((seg.text || "").includes(from)) { seg.text = seg.text.split(from).join(to); count++; }
  }
  renderAll(); markDirty();
  toast(count ? `${count}개 자막에서 바꿨습니다.` : "바꿀 내용을 찾지 못했습니다.");
}

// ══ 타임라인 ═══════════════════════════════════════════════
function renderTimeline() {
  const inner = $("#tl-inner");
  const ruler = $("#tl-ruler");
  const track = $("#tl-track");
  const total = totalDuration();
  const width = Math.max(600, total * pxPerSec);
  inner.style.width = width + "px";

  // 눈금 — 확대 배율에 따라 간격을 바꾼다
  const step = pxPerSec >= 120 ? 1 : pxPerSec >= 60 ? 2 : pxPerSec >= 30 ? 5 : pxPerSec >= 12 ? 10 : 30;
  ruler.innerHTML = "";
  for (let t = 0; t <= total; t += step) {
    const tick = document.createElement("div");
    tick.className = "tl-tick";
    tick.style.left = t * pxPerSec + "px";
    tick.textContent = fmtTime(t).replace(/\.\d$/, "");
    ruler.appendChild(tick);
  }

  // 자막 클립
  track.innerHTML = "";
  const segs = segments();
  if (!segs.length) {
    const empty = document.createElement("div");
    empty.className = "tl-empty";
    empty.textContent = "자막이 만들어지면 여기에 막대로 표시됩니다. 막대를 끌어 시간을 조절할 수 있습니다.";
    track.appendChild(empty);
    return;
  }

  for (const seg of segs) {
    const clip = document.createElement("div");
    clip.className = "tl-clip";
    clip.dataset.id = seg.id;
    if (seg.id === selectedId) clip.classList.add("is-active");
    if (cps(seg) > 11) clip.classList.add("is-warn");
    clip.style.left = seg.start * pxPerSec + "px";
    clip.style.width = Math.max(12, (seg.end - seg.start) * pxPerSec) + "px";
    clip.title = `${fmtTime(seg.start)} → ${fmtTime(seg.end)}\n${seg.text || "(빈 자막)"}\n끌어서 옮기고, 양 끝을 끌어 길이를 바꿉니다.`;

    const label = document.createElement("span");
    label.textContent = seg.text || "(빈 자막)";
    clip.appendChild(label);

    const gl = document.createElement("div"); gl.className = "grip grip-l";
    const gr = document.createElement("div"); gr.className = "grip grip-r";
    clip.append(gl, gr);

    clip.addEventListener("mousedown", (e) => startClipDrag(e, seg, clip));
    clip.addEventListener("click", (e) => { e.stopPropagation(); selectSegment(seg.id, true); scrollToSegmentRow(seg.id); });
    track.appendChild(clip);
  }
}

function startClipDrag(e, seg, clip) {
  e.preventDefault();
  const mode = e.target.classList.contains("grip-l") ? "left"
             : e.target.classList.contains("grip-r") ? "right" : "move";
  const startX = e.clientX;
  const orig = { start: seg.start, end: seg.end };
  let moved = false;

  const onMove = (ev) => {
    const deltaSec = (ev.clientX - startX) / pxPerSec;
    if (Math.abs(ev.clientX - startX) > 2) moved = true;
    if (mode === "move") {
      const shift = Math.max(-orig.start, deltaSec);
      seg.start = Math.round((orig.start + shift) * 10) / 10;
      seg.end = Math.round((orig.end + shift) * 10) / 10;
    } else if (mode === "left") {
      seg.start = clamp(Math.round((orig.start + deltaSec) * 10) / 10, 0, orig.end - 0.1);
    } else {
      seg.end = Math.max(orig.start + 0.1, Math.round((orig.end + deltaSec) * 10) / 10);
    }
    clip.style.left = seg.start * pxPerSec + "px";
    clip.style.width = Math.max(12, (seg.end - seg.start) * pxPerSec) + "px";
  };

  const onUp = () => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    if (!moved) return;
    // 실제 변경을 확정하기 전에 원래 값으로 되돌린 스냅샷을 남긴다
    const after = { start: seg.start, end: seg.end };
    seg.start = orig.start; seg.end = orig.end;
    snapshot();
    seg.start = after.start; seg.end = after.end;
    sortSegments(); renderAll(); markDirty();
  };

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

function updatePlayhead(time) {
  const head = $("#tl-playhead");
  head.style.left = time * pxPerSec + "px";

  // 재생 위치가 화면 밖으로 나가면 따라간다
  const scroll = $("#tl-scroll");
  const x = time * pxPerSec;
  if (x < scroll.scrollLeft || x > scroll.scrollLeft + scroll.clientWidth - 60) {
    scroll.scrollLeft = Math.max(0, x - scroll.clientWidth * 0.4);
  }
}

function setZoom(next) {
  pxPerSec = clamp(next, 3, 300);
  renderTimeline();
  updatePlayhead($("#player").currentTime || 0);
}

function zoomFit() {
  const scroll = $("#tl-scroll");
  setZoom((scroll.clientWidth - 20) / Math.max(1, totalDuration()));
}

function scrollToSegmentRow(id) {
  const row = $(`.seg-item[data-id="${id}"]`);
  if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ══ 플레이어 오버레이 (자막 미리보기 + 위치 끌기) ══════════
function currentSegment(time) {
  return segments().find((s) => time >= s.start && time <= s.end) || null;
}

function updateOverlay(time) {
  const overlay = $("#overlay");
  const seg = currentSegment(time);
  overlay.textContent = seg ? wrapText(seg.text || "") : "";

  // 재생 중인 자막 강조 + 자동 스크롤
  $$(".seg-item").forEach((el) => el.classList.toggle("is-playing", seg && el.dataset.id === seg.id));
}

/** 한 줄 최대 글자수에 맞춰 어절 단위로 줄을 나눈다 (F-11). */
function wrapText(text) {
  const max = project?.style?.max_chars ?? 20;
  const maxLines = project?.style?.max_lines ?? 2;
  const words = text.split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const w of words) {
    if (!line) { line = w; }
    else if ((line + " " + w).length <= max) { line += " " + w; }
    else { lines.push(line); line = w; }
  }
  if (line) lines.push(line);
  return lines.slice(0, maxLines).join("\n");
}

function applyOverlayStyle() {
  const overlay = $("#overlay");
  const st = project?.style;
  if (!st) return;

  const player = $("#player");
  const height = player.clientHeight || 360;
  const scale = height / 720;

  const outline = st.outline || { color: "#000", width: 2 };
  const shadows = [];
  const w = (outline.width || 0) * scale;
  if (w > 0) {
    for (const [dx, dy] of [[-1,-1],[0,-1],[1,-1],[-1,0],[1,0],[-1,1],[0,1],[1,1]])
      shadows.push(`${(dx * w).toFixed(2)}px ${(dy * w).toFixed(2)}px 0 ${outline.color}`);
  }
  if (st.shadow?.enabled) {
    const d = (st.shadow.depth || 0) * scale;
    shadows.push(`${d.toFixed(2)}px ${d.toFixed(2)}px ${(d * 1.6).toFixed(2)}px rgba(0,0,0,.85)`);
  }

  overlay.style.fontFamily = `"${st.font}", "Malgun Gothic", sans-serif`;
  overlay.style.fontSize = `${(st.size * scale).toFixed(1)}px`;
  overlay.style.fontWeight = st.bold ? "700" : "400";
  overlay.style.fontStyle = st.italic ? "italic" : "normal";
  overlay.style.color = st.color;
  overlay.style.textAlign = st.align;
  overlay.style.letterSpacing = `${((st.letter_spacing || 0) * scale).toFixed(2)}px`;
  overlay.style.lineHeight = String(st.line_height || 1.3);
  overlay.style.textShadow = shadows.length ? shadows.join(", ") : "none";

  if (st.bg?.enabled) {
    const h = st.bg.color.replace("#", "");
    const rgb = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)).join(",");
    overlay.style.backgroundColor = `rgba(${rgb},${st.bg.opacity})`;
    overlay.style.padding = `${(0.18 * st.size * scale).toFixed(1)}px ${(0.5 * st.size * scale).toFixed(1)}px`;
    overlay.style.borderRadius = `${(0.12 * st.size * scale).toFixed(1)}px`;
  } else {
    overlay.style.backgroundColor = "transparent";
    overlay.style.padding = "0";
  }

  const [x, y] = resolvedPosition(st);
  overlay.style.left = `${x}%`;
  overlay.style.top = `${y}%`;
}

function resolvedPosition(st) {
  const pos = st.position || {};
  if (pos.mode === "custom") return [pos.x ?? 50, pos.y ?? 88];
  const y = { top: 12, middle: 50, bottom: 88 }[pos.preset || "bottom"] ?? 88;
  const x = { left: 20, center: 50, right: 80 }[st.align || "center"] ?? 50;
  return [x, y];
}

/** 자막을 마우스로 끌어 원하는 위치에 놓는다. */
function wireOverlayDrag() {
  const overlay = $("#overlay");
  const box = $("#video-box");
  const readout = $("#drag-readout");

  overlay.addEventListener("mousedown", (e) => {
    if (!project) return;
    e.preventDefault();
    overlay.classList.add("is-dragging");
    readout.hidden = false;

    const rect = box.getBoundingClientRect();
    const onMove = (ev) => {
      const x = clamp(((ev.clientX - rect.left) / rect.width) * 100, 0, 100);
      const y = clamp(((ev.clientY - rect.top) / rect.height) * 100, 0, 100);
      project.style.position = { mode: "custom", preset: project.style.position?.preset || "bottom", x: +x.toFixed(1), y: +y.toFixed(1) };
      overlay.style.left = `${x}%`;
      overlay.style.top = `${y}%`;
      readout.textContent = `가로 ${x.toFixed(1)}%  세로 ${y.toFixed(1)}%`;
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      overlay.classList.remove("is-dragging");
      readout.hidden = true;
      snapshot(); syncStyleInputs(); markDirty();
      toast("자막 위치를 옮겼습니다. [기본 위치로 되돌리기]로 되돌릴 수 있습니다.");
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

// ══ 스타일 패널 ════════════════════════════════════════════
async function renderStylePanel() {
  // 글꼴 목록
  try {
    const { fonts } = await api("/api/styles/fonts");
    const select = $("#style-font");
    select.innerHTML = "";
    for (const f of fonts) {
      const opt = document.createElement("option");
      opt.value = f.name; opt.textContent = f.label;
      select.appendChild(opt);
    }
  } catch (_) { /* 글꼴 목록을 못 받아도 나머지는 동작한다 */ }

  // 프리셋 카드
  try {
    presets = await api("/api/styles/presets");
    const grid = $("#preset-grid");
    grid.innerHTML = "";
    for (const p of [...presets.builtin, ...presets.user]) {
      const card = document.createElement("button");
      card.className = "preset";
      card.dataset.key = p.key;
      card.title = p.desc;
      card.innerHTML = `<div class="p-label">${p.label}</div><div class="p-desc">${p.desc}</div>`;
      card.addEventListener("click", () => {
        snapshot();
        project.style = JSON.parse(JSON.stringify(p.style));
        syncStyleInputs(); applyOverlayStyle(); renderAll(); markDirty();
        toast(`'${p.label}' 프리셋을 적용했습니다.`);
      });
      grid.appendChild(card);
    }
  } catch (_) {}

  syncStyleInputs();
}

/** project.style 값을 우측 패널 입력칸들에 반영한다. */
function syncStyleInputs() {
  const st = project?.style;
  if (!st) return;
  const set = (sel, value) => { const el = $(sel); if (el) el.value = value; };

  set("#style-font", st.font);
  set("#style-size", st.size);
  set("#style-spacing", st.letter_spacing);
  set("#style-lineheight", st.line_height);
  set("#style-align", st.align);
  set("#style-color", st.color);
  set("#style-outline-color", st.outline.color);
  set("#style-outline-width", st.outline.width);
  set("#style-shadow-depth", st.shadow.depth);
  set("#style-bg-color", st.bg.color);
  set("#style-bg-opacity", st.bg.opacity);
  set("#style-maxchars", st.max_chars);
  set("#style-maxlines", st.max_lines);

  $("#style-shadow").checked = !!st.shadow.enabled;
  $("#style-bg").checked = !!st.bg.enabled;
  $("#style-bold").classList.toggle("is-on", !!st.bold);
  $("#style-italic").classList.toggle("is-on", !!st.italic);

  $("#outline-val").textContent = Number(st.outline.width).toFixed(1);
  $("#shadow-val").textContent = Number(st.shadow.depth).toFixed(1);
  $("#bgop-val").textContent = Number(st.bg.opacity).toFixed(2);

  const [x, y] = resolvedPosition(st);
  set("#style-pos-x", x.toFixed(1));
  set("#style-pos-y", y.toFixed(1));

  const isCustom = st.position?.mode === "custom";
  $$(".pos-btn").forEach((b) => b.classList.toggle("is-active", !isCustom && b.dataset.pos === st.position?.preset));
  $$(".preset").forEach((c) => c.classList.toggle("is-active", c.dataset.key === st.preset));
}

function wireStylePanel() {
  const change = (sel, apply, live = false) => {
    const el = $(sel);
    if (!el) return;
    const handler = () => { apply(el.value, el.checked); applyOverlayStyle(); syncStyleInputs(); markDirty(); };
    el.addEventListener(live ? "input" : "change", handler);
    if (live) el.addEventListener("change", () => snapshot());
    else el.addEventListener("change", () => {}, { once: false });
  };

  change("#style-font", (v) => { project.style.font = v; });
  change("#style-size", (v) => { project.style.size = clamp(parseInt(v, 10) || 42, 12, 120); }, true);
  change("#style-spacing", (v) => { project.style.letter_spacing = parseFloat(v) || 0; }, true);
  change("#style-lineheight", (v) => { project.style.line_height = parseFloat(v) || 1.3; }, true);
  change("#style-align", (v) => { project.style.align = v; });
  change("#style-color", (v) => { project.style.color = v; }, true);
  change("#style-outline-color", (v) => { project.style.outline.color = v; }, true);
  change("#style-outline-width", (v) => { project.style.outline.width = parseFloat(v); }, true);
  change("#style-shadow-depth", (v) => { project.style.shadow.depth = parseFloat(v); }, true);
  change("#style-bg-color", (v) => { project.style.bg.color = v; }, true);
  change("#style-bg-opacity", (v) => { project.style.bg.opacity = parseFloat(v); }, true);
  change("#style-maxchars", (v) => { project.style.max_chars = clamp(parseInt(v, 10) || 20, 8, 40); });
  change("#style-maxlines", (v) => { project.style.max_lines = clamp(parseInt(v, 10) || 2, 1, 3); });

  $("#style-shadow").addEventListener("change", (e) => {
    snapshot(); project.style.shadow.enabled = e.target.checked;
    applyOverlayStyle(); markDirty();
  });
  $("#style-bg").addEventListener("change", (e) => {
    snapshot(); project.style.bg.enabled = e.target.checked;
    applyOverlayStyle(); markDirty();
  });
  $("#style-bold").addEventListener("click", () => {
    snapshot(); project.style.bold = !project.style.bold;
    syncStyleInputs(); applyOverlayStyle(); markDirty();
  });
  $("#style-italic").addEventListener("click", () => {
    snapshot(); project.style.italic = !project.style.italic;
    syncStyleInputs(); applyOverlayStyle(); markDirty();
  });

  $$(".pos-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      snapshot();
      project.style.position = { mode: "preset", preset: btn.dataset.pos, x: 50, y: 88 };
      syncStyleInputs(); applyOverlayStyle(); markDirty();
    });
  });

  for (const [sel, key] of [["#style-pos-x", "x"], ["#style-pos-y", "y"]]) {
    $(sel).addEventListener("change", (e) => {
      const value = clamp(parseFloat(e.target.value) || 0, 0, 100);
      const [cx, cy] = resolvedPosition(project.style);
      snapshot();
      project.style.position = { mode: "custom", preset: project.style.position?.preset || "bottom", x: key === "x" ? value : cx, y: key === "y" ? value : cy };
      syncStyleInputs(); applyOverlayStyle(); markDirty();
    });
  }

  $("#btn-pos-reset").addEventListener("click", () => {
    snapshot();
    project.style.position = { mode: "preset", preset: "bottom", x: 50, y: 88 };
    syncStyleInputs(); applyOverlayStyle(); markDirty();
    toast("자막을 기본 위치(아래)로 되돌렸습니다.");
  });

  $("#btn-save-preset").addEventListener("click", async () => {
    const name = $("#preset-name").value.trim();
    if (!name) { toast("프리셋 이름을 입력해 주세요.", { error: true }); return; }
    try {
      await api("/api/styles/presets", { method: "POST", body: JSON.stringify({ name, style: project.style }) });
      $("#preset-name").value = "";
      await renderStylePanel();
      toast(`'${name}' 프리셋을 저장했습니다.`);
    } catch (err) { toast(err.message, { error: true }); }
  });

  $("#chk-safe-area").addEventListener("change", (e) => { $("#safe-area").hidden = !e.target.checked; });
}

// ══ 나레이션 패널 ══════════════════════════════════════════
async function renderNarrationPanel() {
  const n = project?.narration;
  if (n) {
    $("#tts-gap").value = n.gap ?? 0.3;
    $("#tts-origvol").value = n.original_audio_volume ?? 30;
    $("#tts-ducking").checked = !!n.ducking;
    const rate = parseInt(String(n.global_rate || "+0%"), 10) || 0;
    $("#tts-rate").value = rate; $("#rate-val").textContent = `${rate >= 0 ? "+" : ""}${rate}%`;
  }

  if (!voices.length) {
    try {
      const data = await api("/api/tts/voices");
      voices = data.voices;
      $("#voice-count").textContent =
        `한국어 전용 ${data.korean_native_count}개 · 한국어 가능 ${data.korean_capable_count}개 · 전체 ${data.total}개`;
    } catch (err) {
      $("#voice-count").textContent = `목소리 목록을 못 받았습니다: ${err.message}`;
      return;
    }
  }
  renderVoiceList();
}

function renderVoiceList() {
  const list = $("#voice-list");
  const needle = $("#voice-search").value.trim().toLowerCase();
  const filter = $("#voice-filter").value;
  const current = project?.narration?.voice;

  let items = voices;
  if (filter === "korean") items = items.filter((v) => v.speaks_korean);
  else if (filter === "ko") items = items.filter((v) => v.locale.startsWith("ko"));
  if (needle) items = items.filter((v) => (v.label + v.id + v.locale).toLowerCase().includes(needle));

  list.innerHTML = "";
  if (!items.length) {
    list.innerHTML = '<div class="hint" style="padding:12px">조건에 맞는 목소리가 없습니다.</div>';
    return;
  }

  for (const v of items.slice(0, 120)) {
    const row = document.createElement("div");
    row.className = "voice-item";
    if (v.id === current) row.classList.add("is-active");

    const label = document.createElement("div");
    label.className = "v-label";
    label.innerHTML = v.locale.startsWith("ko")
      ? `<span class="v-native">한국어</span> ${v.label}`
      : v.label;

    const play = document.createElement("button");
    play.className = "v-play"; play.textContent = "▶ 듣기";
    play.title = "이 목소리를 3초 미리듣기";
    play.addEventListener("click", (e) => { e.stopPropagation(); previewVoice(v.id, play); });

    row.addEventListener("click", () => {
      project.narration.voice = v.id;
      renderVoiceList(); markDirty();
      toast(`목소리를 '${v.label}'로 바꿨습니다.`);
    });

    row.append(label, play);
    list.appendChild(row);
  }
  if (items.length > 120) {
    const more = document.createElement("div");
    more.className = "hint";
    more.style.padding = "8px 10px";
    more.textContent = `… 외 ${items.length - 120}개. 검색으로 좁혀 보세요.`;
    list.appendChild(more);
  }
}

let previewAudio = null;
async function previewVoice(voiceId, button) {
  const original = button.textContent;
  button.textContent = "만드는 중…"; button.disabled = true;
  try {
    const res = await fetch("/api/tts/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice: voiceId,
        text: "안녕하세요. 이 목소리로 나레이션을 만들어 드립니다.",
        rate: rateString(),
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `미리듣기 실패 (${res.status})`);
    }
    const blob = await res.blob();
    if (previewAudio) { previewAudio.pause(); URL.revokeObjectURL(previewAudio.src); }
    previewAudio = new Audio(URL.createObjectURL(blob));
    previewAudio.play();
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    button.textContent = original; button.disabled = false;
  }
}

function rateString() {
  const v = parseInt($("#tts-rate").value, 10) || 0;
  return `${v >= 0 ? "+" : ""}${v}%`;
}

function wireNarrationPanel() {
  $("#voice-search").addEventListener("input", renderVoiceList);
  $("#voice-filter").addEventListener("change", renderVoiceList);

  const bindRange = (sel, valSel, unit, key) => {
    $(sel).addEventListener("input", (e) => {
      const v = parseInt(e.target.value, 10);
      $(valSel).textContent = `${v >= 0 ? "+" : ""}${v}${unit}`;
      if (project) { project.narration[key] = `${v >= 0 ? "+" : ""}${v}${unit}`; markDirty(); }
    });
  };
  bindRange("#tts-rate", "#rate-val", "%", "global_rate");
  bindRange("#tts-pitch", "#pitch-val", "Hz", "global_pitch");
  bindRange("#tts-volume", "#vol-val", "%", "global_volume");

  $("#tts-gap").addEventListener("change", (e) => { project.narration.gap = parseFloat(e.target.value) || 0; markDirty(); });
  $("#tts-origvol").addEventListener("change", (e) => { project.narration.original_audio_volume = parseInt(e.target.value, 10) || 0; markDirty(); });
  $("#tts-ducking").addEventListener("change", (e) => { project.narration.ducking = e.target.checked; markDirty(); });

  $("#btn-record-voice").addEventListener("click", () => {
    toast("내 목소리 나레이션은 엔진 검토를 마치는 대로 연결됩니다.");
  });
}

// ══ 사전 탭 ════════════════════════════════════════════════
function wireDictionary() {
  const add = (fromSel, toSel, listKey, listSel) => () => {
    const from = $(fromSel).value.trim();
    const to = $(toSel).value.trim();
    if (!from) { toast("바꿀 말을 입력해 주세요.", { error: true }); return; }
    project[listKey] = project[listKey] || [];
    project[listKey].push({ from, to });
    $(fromSel).value = ""; $(toSel).value = "";
    renderDict(listKey, listSel); markDirty();
  };
  $("#btn-dict-add").addEventListener("click", add("#dict-from", "#dict-to", "dictionary", "#dict-list"));
  $("#btn-read-add").addEventListener("click", add("#read-from", "#read-to", "read_dictionary", "#read-list"));
}

function renderDict(key, sel) {
  const list = $(sel);
  const items = project?.[key] ?? [];
  list.innerHTML = "";
  for (let i = 0; i < items.length; i++) {
    const li = document.createElement("li");
    li.textContent = `${items[i].from} → ${items[i].to}`;
    const del = document.createElement("button");
    del.className = "d-del"; del.textContent = "✕";
    del.addEventListener("click", () => { items.splice(i, 1); renderDict(key, sel); markDirty(); });
    li.appendChild(del);
    list.appendChild(li);
  }
}

// ══ 상황별 안내 문구 ═══════════════════════════════════════
const HELP_TEXT = {
  idle: "자막을 클릭하면 그 시점으로 이동합니다. 글자를 클릭하면 바로 고칠 수 있습니다.",
  selected: "Enter로 글 고치기 · ↑↓로 다른 자막 선택 · Delete로 삭제 · 아래 막대를 끌어 시간 조절",
  edit: "글 중간에 커서를 두고 Ctrl+Enter를 누르면 그 자리에서 두 개로 나뉩니다. Enter로 확정, Esc로 취소.",
  time: "01:23.4 형식으로 입력하세요. 좌우 ◀▶ 버튼은 0.1초씩 움직입니다.",
};
function setHelp(kind) { $("#help-bar").textContent = HELP_TEXT[kind] || HELP_TEXT.idle; }

// ══ 처음 한 번만 보여주는 사용법 ═══════════════════════════
const COACH_KEY = "moviefit.coach.v1";
function maybeShowCoach() {
  if (localStorage.getItem(COACH_KEY) === "done") return;
  $("#coach").hidden = false;
}
function wireCoach() {
  $("#coach-close").addEventListener("click", () => {
    if ($("#coach-dont-show").checked) localStorage.setItem(COACH_KEY, "done");
    $("#coach").hidden = true;
  });
  $("#btn-help").addEventListener("click", () => { $("#shortcuts").hidden = false; });
  $("#shortcuts-close").addEventListener("click", () => { $("#shortcuts").hidden = true; });
  $("#shortcuts").addEventListener("click", (e) => { if (e.target.id === "shortcuts") $("#shortcuts").hidden = true; });
}

// ══ 대본 통계 ══════════════════════════════════════════════
function splitSentences(text) {
  return text.split(/(?<=[.!?。！？])\s+|\n+/).map((s) => s.trim()).filter(Boolean);
}
function updateScriptStats() {
  const text = $("#script-input").value;
  const chars = text.replace(/\s/g, "").length;
  const sentences = splitSentences(text);
  // 한국어 나레이션은 대략 초당 5자 정도로 읽힌다 (실제 길이는 생성 후 실측한다)
  const estimate = Math.round(chars / 5 + sentences.length * (project?.narration?.gap ?? 0.3));
  $("#script-stats").textContent = `${chars}자 · 문장 ${sentences.length}개 · 예상 ${estimate}초`;
}

// ══ 시작 화면 연결 ═════════════════════════════════════════
function wireStartScreen() {
  const pick = async () => {
    try {
      const result = await api("/api/system/pick-file", { method: "POST" });
      if (result.cancelled) return;
      await createProject({ name: result.name.replace(/\.[^.]+$/, ""), video_path: result.path, mode: "video" });
    } catch (err) { toast(err.message, { error: true }); }
  };

  const zone = $("#drop-zone");
  zone.addEventListener("click", pick);
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); zone.classList.remove("is-over");
    toast("브라우저 보안상 끌어다 놓기로는 파일 위치를 알 수 없습니다. 상자를 눌러 파일을 선택해 주세요.");
  });

  $("#btn-manual-open").addEventListener("click", async () => {
    const path = $("#manual-path").value.trim().replace(/^"|"$/g, "");
    if (!path) { toast("파일 경로를 입력해 주세요.", { error: true }); return; }
    await createProject({ name: path.split(/[\\/]/).pop().replace(/\.[^.]+$/, ""), video_path: path, mode: "video" });
  });

  $("#btn-start-script").addEventListener("click", () => {
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    createProject({ name: `${stamp}_나레이션`, video_path: null, mode: "script" });
  });
}

// ══ 작업 화면 연결 ═════════════════════════════════════════
function wireEditor() {
  $("#btn-home").addEventListener("click", async () => { clearTimeout(saveTimer); await saveNow(); showStart(); });
  $("#project-name").addEventListener("input", (e) => { project.name = e.target.value; markDirty(); });
  $("#mode-video").addEventListener("click", () => setMode("video"));
  $("#mode-script").addEventListener("click", () => setMode("script"));

  $("#script-input").addEventListener("input", (e) => { project.script = e.target.value; updateScriptStats(); markDirty(); });
  $("#btn-split-script").addEventListener("click", () => {
    const list = splitSentences($("#script-input").value);
    if (!list.length) { toast("대본이 비어 있습니다.", { error: true }); return; }
    alert(`문장 ${list.length}개로 나뉩니다:\n\n` + list.map((s, i) => `${i + 1}. ${s}`).join("\n"));
  });

  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
      $$(".tab-page").forEach((p) => { p.hidden = p.dataset.page !== btn.dataset.tab; });
    });
  });

  $("#stt-language").addEventListener("change", (e) => { project.stt.language = e.target.value; markDirty(); });
  $("#stt-model").addEventListener("change", (e) => { project.stt.model = e.target.value; markDirty(); });

  // 아직 연결되지 않은 기능은 솔직하게 알린다
  $("#btn-stt").addEventListener("click", () => toast("자막 자동 생성은 Phase 1에서 연결됩니다."));
  $("#btn-tts").addEventListener("click", () => toast("나레이션 생성은 Phase 2에서 연결됩니다."));
  $("#btn-export").addEventListener("click", () => toast("내보내기는 Phase 1에서 연결됩니다."));
  $("#btn-to-script").addEventListener("click", () => {
    if (!segments().length) { toast("옮길 자막이 없습니다.", { error: true }); return; }
    project.script = segments().map((s) => s.text).filter(Boolean).join("\n");
    $("#script-input").value = project.script;
    updateScriptStats(); setMode("script"); markDirty();
    toast("자막을 대본으로 옮겼습니다.");
  });

  // 편집기 도구
  $("#btn-seg-add").addEventListener("click", addSegment);
  $("#btn-undo").addEventListener("click", undo);
  $("#btn-redo").addEventListener("click", redo);
  $("#btn-shift-all").addEventListener("click", shiftAll);
  $("#btn-check").addEventListener("click", checkSegments);
  $("#seg-search").addEventListener("input", (e) => renderSegments(e.target.value));
  $("#btn-toggle-replace").addEventListener("click", () => {
    const hidden = $("#seg-replace").hidden;
    $("#seg-replace").hidden = !hidden;
    $("#btn-replace-all").hidden = !hidden;
  });
  $("#btn-replace-all").addEventListener("click", replaceAll);

  // 타임라인
  $("#tl-zoom-in").addEventListener("click", () => setZoom(pxPerSec * 1.5));
  $("#tl-zoom-out").addEventListener("click", () => setZoom(pxPerSec / 1.5));
  $("#tl-zoom-fit").addEventListener("click", zoomFit);
  $("#tl-track").addEventListener("click", (e) => {
    if (e.target.closest(".tl-clip")) return;
    const rect = $("#tl-inner").getBoundingClientRect();
    const time = (e.clientX - rect.left) / pxPerSec;
    const p = $("#player");
    if (p.src) p.currentTime = clamp(time, 0, p.duration || time);
    else updatePlayhead(Math.max(0, time));
  });

  // 플레이어
  const player = $("#player");
  player.addEventListener("timeupdate", () => {
    $("#time-now").textContent = fmtTime(player.currentTime);
    updateOverlay(player.currentTime);
    updatePlayhead(player.currentTime);
  });
  player.addEventListener("loadedmetadata", () => {
    $("#time-total").textContent = fmtTime(player.duration);
    applyOverlayStyle(); zoomFit();
  });
  player.addEventListener("error", () => {
    if (player.getAttribute("src")) toast("영상을 재생할 수 없습니다. 파일이 옮겨졌거나 지원하지 않는 형식일 수 있습니다.", { error: true });
  });
  $("#btn-play").addEventListener("click", () => (player.paused ? player.play() : player.pause()));
  player.addEventListener("play", () => ($("#btn-play").textContent = "⏸"));
  player.addEventListener("pause", () => ($("#btn-play").textContent = "▶"));
  $("#playback-rate").addEventListener("change", (e) => { player.playbackRate = parseFloat(e.target.value); });
  $("#btn-prev-seg").addEventListener("click", () => stepSegment(-1));
  $("#btn-next-seg").addEventListener("click", () => stepSegment(+1));
  window.addEventListener("resize", () => { applyOverlayStyle(); });

  wireOverlayDrag();
  wireStylePanel();
  wireNarrationPanel();
  wireDictionary();
  wireCoach();
  wireShortcuts();

  window.addEventListener("beforeunload", () => {
    if (saveTimer && project) {
      clearTimeout(saveTimer);
      navigator.sendBeacon(
        `/api/projects/${encodeURIComponent(project.id)}`,
        new Blob([JSON.stringify(project)], { type: "application/json" })
      );
    }
  });
}

function stepSegment(direction) {
  const segs = segments();
  if (!segs.length) return;
  let i = segIndex(selectedId);
  i = i < 0 ? (direction > 0 ? 0 : segs.length - 1) : clamp(i + direction, 0, segs.length - 1);
  selectSegment(segs[i].id, true);
  scrollToSegmentRow(segs[i].id);
}

function wireShortcuts() {
  document.addEventListener("keydown", (e) => {
    if ($("#view-editor").hidden) return;
    const el = document.activeElement;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName);
    const player = $("#player");

    if (e.ctrlKey && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); return; }
    if (e.ctrlKey && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    if (e.ctrlKey && e.key.toLowerCase() === "f") { e.preventDefault(); $("#seg-search").focus(); return; }
    if (e.ctrlKey && e.key.toLowerCase() === "s") { e.preventDefault(); clearTimeout(saveTimer); saveNow(); toast("저장했습니다."); return; }

    if (typing) return;

    if (e.key === " ") { e.preventDefault(); player.paused ? player.play() : player.pause(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); player.currentTime -= e.shiftKey ? 0.1 : 1; }
    else if (e.key === "ArrowRight") { e.preventDefault(); player.currentTime += e.shiftKey ? 0.1 : 1; }
    else if (e.key === "ArrowUp") { e.preventDefault(); stepSegment(-1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); stepSegment(+1); }
    else if (e.key === "Enter" && selectedId) {
      e.preventDefault();
      const box = $(`.seg-item[data-id="${selectedId}"] .seg-text`);
      if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
    }
    else if (e.key === "Delete" && selectedId) { e.preventDefault(); deleteSegment(selectedId); }
  });
}

// ══ PWA ════════════════════════════════════════════════════
function wirePWA() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  let installPrompt = null;
  const btn = $("#btn-install");
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; btn.hidden = false; });
  btn.addEventListener("click", async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null; btn.hidden = true;
  });
}

// ══ 시작 ═══════════════════════════════════════════════════
async function boot() {
  wireStartScreen();
  wireEditor();
  wirePWA();
  setHelp("idle");

  try {
    const info = await api("/api/system/info");
    $("#env-info").textContent = `버전 ${info.version} · 파이썬 ${info.python}`;
  } catch (_) {}

  const requested = new URLSearchParams(location.search).get("project");
  if (requested) await openProject(requested);
  else await loadRecent();
}

boot();
