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

let waveformPeaks = null;  // 소리 파형 데이터 (0~1 배열)
let exportWarning = null;  // 내보내기 전에 알려야 할 경고 (예: 나레이션이 영상보다 김)
let abLoop = null;         // 구간 반복 {start, end} 또는 {start} (끝을 찍는 중)
let tapSyncOn = false;     // 두드려 맞추기 모드

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ══ 서버 통신 ══════════════════════════════════════════════
async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch (_) {
    // 서버에 닿지 못하면 브라우저가 "Failed to fetch" 라는 영어 문구를 던진다.
    // 사용자에게는 아무 뜻도 없는 말이므로 무슨 일이고 무엇을 하면 되는지로 바꾼다.
    // (프로그램이 켜지는 도중이거나, 검은 명령 창이 닫혔을 때 실제로 나온다)
    throw new Error(
      "프로그램과 연결이 끊겼습니다. 검은 명령 창이 켜져 있는지 확인한 뒤 F5로 새로고침해 주세요."
    );
  }
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
// 편집하면 2초 뒤에 저절로 저장된다. 그 2초를 기다리기 싫으면 [저장됨] 단추를 누른다 (F-D).
let justSavedTimer = null;

/** 단추에 마우스를 올렸을 때 뜨는 설명. 마지막으로 저장한 시각을 함께 보여 준다. */
function refreshSaveTip() {
  const el = $("#save-state");
  if (!el) return;
  const when = project && project.updated_at
    ? `마지막 저장: ${project.updated_at}`
    : "아직 저장한 적이 없습니다";
  el.title = `누르면 기다리지 않고 지금 바로 저장합니다\n${when}`;
}

function markDirty() {
  if (!project) return;
  const state = $("#save-state");
  state.textContent = "저장 중…";
  state.classList.add("is-saving");
  state.classList.remove("is-just-saved");
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveNow(), 2000);
}

/** 지금 즉시 저장한다. flash를 켜면 저장이 끝난 뒤 단추가 잠깐 밝아지고 알림이 뜬다. */
async function saveNow({ flash = false } = {}) {
  if (!project) return false;
  const state = $("#save-state");
  clearTimeout(saveTimer);   // 손으로 눌렀으면 예약해 둔 자동 저장은 필요 없다
  saveTimer = null;
  state.textContent = "저장 중…";
  state.classList.add("is-saving");
  try {
    const saved = await api(`/api/projects/${encodeURIComponent(project.id)}`, {
      method: "PUT", body: JSON.stringify(project),
    });
    project.updated_at = saved.updated_at;
    state.textContent = "저장됨";
    refreshSaveTip();
    if (flash) {
      state.classList.add("is-just-saved");
      clearTimeout(justSavedTimer);
      justSavedTimer = setTimeout(() => state.classList.remove("is-just-saved"), 1400);
      toast(`저장했습니다. (${project.updated_at})`);
    }
    return true;
  } catch (err) {
    state.textContent = "저장 실패";
    toast(`저장하지 못했습니다: ${err.message}`, { error: true });
    return false;
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

// 최근 목록에 "무엇으로 만든 프로젝트인가"를 한 낱말로 보여 준다.
// 옛 프로젝트에는 image_count·audio_path 가 없으므로 없을 때를 기본으로 둔다.
function recentKind(p) {
  if (p.image_count) return p.audio_path ? `음원+사진 ${p.image_count}장` : `사진 ${p.image_count}장`;
  if (p.audio_path) return "음원";
  return p.mode === "script" ? "대본" : "영상";
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
      meta.textContent = `${recentKind(p)} · 자막 ${p.segment_count}개 · ${p.updated_at}`;

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
async function createProject({ name, video_path, mode, image_paths, audio_path }) {
  try {
    project = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        name,
        video_path: video_path || null,
        mode: mode || "video",
        image_paths: image_paths || null,
        audio_path: audio_path || null,
      }),
    });
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
  refreshSaveTip();
  setMode(project.mode, false);

  // 화면비 설정이 없던 옛 프로젝트도 열리게 한다 (기본값은 '원본 그대로'라 동작이 같다)
  project.output = normalizeOutput(project.output);

  const player = $("#player");
  const box = $("#video-box");
  if (project.video_path) {
    player.src = `/media/project/${encodeURIComponent(project.id)}/video`;
    player.hidden = false; player.controls = true;
    $("#no-video").hidden = true;
    box.classList.remove("is-empty");
    $("#file-info").textContent = project.video_path;
    loadWaveform();
    refreshPhotoStage();
  } else if (hasImages() || project.audio_path) {
    // 사진·음원 프로젝트: <video> 는 감춘 채 시계와 소리만 맡는다.
    player.hidden = true;
    $("#no-video").hidden = true;
    box.classList.remove("is-empty");
    if (project.audio_path) {
      player.src = `/media/project/${encodeURIComponent(project.id)}/audio`;
      $("#file-info").textContent = project.audio_path;
      loadWaveform();
    } else {
      waveformPeaks = null;
    }
    if (!project.audio_path) {
      $("#file-info").textContent = `사진 ${projectImages().length}장`;
    }
    refreshPhotoStage({ reloadClock: !project.audio_path });
  } else {
    player.removeAttribute("src"); player.hidden = true;
    $("#no-video").hidden = false;
    // 영상이 없으면 상자에 폭이 없어 글자가 세로로 쓰이므로 상자를 펼친다
    box.classList.add("is-empty");
    $("#file-info").textContent = "파일 없음 (나레이션 작업)";
    waveformPeaks = null;
    refreshPhotoStage();
  }

  refreshFilmstrip();  // 영상이 있는 프로젝트만 띠를 깐다 (안에서 판단한다)
  renderBgm();

  $("#script-input").value = project.script || "";
  updateScriptStats();
  $("#stt-language").value = project.stt?.language ?? "ko";
  $("#stt-model").value = project.stt?.model ?? "small";

  renderStylePanel();
  renderNarrationPanel();
  syncAspectInputs();
  applyFrameGuide();   // 영상 크기를 알게 되면 loadedmetadata 에서 한 번 더 그린다
  renderAll();
  refreshUndoButtons();
}

function renderAll() {
  renderSegments();
  renderTimelineAll();
  syncFxPanel();
  applyOverlayStyle();
  updateOverlay($("#player").currentTime || 0);
}

// ══ 사진 영상 (Phase 6) ═══════════════════════════════════
//
// 사진 프로젝트에는 재생할 영상 파일이 없다. 그런데 이 화면의 거의 모든 것이
// <video> 의 재생 위치에 매달려 있다 — 자막 오버레이, 타임라인 재생 머리,
// 두드려 맞추기, A-B 구간 반복. <video> 를 없애면 그것들이 전부 죽는다.
//
// 그래서 <video> 를 **시계와 소리 담당**으로 남긴다.
//   · 음원이 있으면 → mp3 를 넣는다 (브라우저는 <video> 로 소리 파일을 잘 재생한다)
//   · 소리가 없으면 → 길이만 같은 **무음 소리**를 만들어 넣는다
// 이렇게 하면 재생·탐색·시각 표시 코드를 한 줄도 고치지 않아도 그대로 살아난다.

const CANVAS_SIZES = { "16:9": [1920, 1080], "9:16": [1080, 1920], "1:1": [1080, 1080] };
const DEFAULT_CANVAS_ASPECT = "16:9";

let photoTimeline = [];      // [{index, path, start, end}]
let silentClockUrl = null;   // 무음 소리의 임시 주소 (다 쓰면 반드시 반납한다)
let shownPhotoIndex = -1;

function projectImages() { return (project && project.images) || []; }
function hasImages() { return projectImages().length > 0; }
function hasOwnAudio() { return !!(project && project.audio_path); }

/** 사진들이 들어갈 화면 크기. 서버 slideshow.canvas_of() 와 **같은 규칙**이어야 한다. */
function projectCanvas() {
  const conf = currentOutput();
  let aspect = conf.aspect;
  if (aspect === "source") {
    const c = project && project.canvas;
    if (c && c.width > 0 && c.height > 0) return { width: c.width, height: c.height };
    aspect = DEFAULT_CANVAS_ASPECT;
  }
  const size = CANVAS_SIZES[aspect] || CANVAS_SIZES[DEFAULT_CANVAS_ASPECT];
  return { width: size[0], height: size[1] };
}

/** 0.5를 항상 위로 올리는 소수 셋째 자리 반올림 (서버 slideshow._round3 과 같아야 한다). */
function round3(v) { return Math.floor(v * 1000 + 0.5) / 1000; }

/** 사진마다 "몇 초 동안 보이는가"를 확정한다.
 *  서버 slideshow.resolve_durations() 를 그대로 옮긴 것이며, 두 계산이 어긋나면
 *  미리보기와 내보낸 영상의 사진이 달라진다. tests/phase6_test.py 가 둘을 대조한다. */
function resolveImageDurations() {
  const images = projectImages();
  if (!images.length) return [];

  const segs = segments();
  const starts = {};
  for (const seg of segs) starts[String(seg.id)] = Number(seg.start) || 0;
  const anchored = images.some((img) => String(img.seg_id || "") in starts);
  if (!anchored) return images.map((img) => Object.assign({}, img));

  let lastEnd = 0;
  for (const seg of segs) lastEnd = Math.max(lastEnd, Number(seg.end) || 0);

  const timed = [];
  let clock = 0;
  images.forEach((img, index) => {
    const item = Object.assign({}, img);
    const key = String(item.seg_id || "");
    if (key in starts) clock = starts[key];
    timed.push({ start: clock, index, item });
    clock += Math.max(0.05, Number(item.duration) || 0.05);
  });
  timed.sort((a, b) => (a.start - b.start) || (a.index - b.index));

  const resolved = timed.map((row, order) => {
    const nextStart = order + 1 < timed.length
      ? timed[order + 1].start
      : Math.max(lastEnd, row.start + Math.max(0.05, Number(row.item.duration) || 0.05));
    row.item.duration = Math.max(0.05, round3(nextStart - row.start));
    return row.item;
  });
  if (resolved.length && timed[0].start > 0.001) {
    resolved[0].duration = round3(Number(resolved[0].duration) + timed[0].start);
  }
  return resolved;
}

/** 사진들의 시간표를 다시 만든다. 사진이나 자막이 바뀔 때마다 부른다. */
function rebuildPhotoTimeline() {
  const resolved = resolveImageDurations();
  const byPath = new Map();
  projectImages().forEach((img, i) => { if (!byPath.has(img.id)) byPath.set(img.id, i); });

  let clock = 0;
  photoTimeline = resolved.map((img) => {
    const start = clock;
    clock += Math.max(0.05, Number(img.duration) || 0.05);
    return {
      index: byPath.has(img.id) ? byPath.get(img.id) : 0,
      path: img.path,
      start,
      end: clock,
    };
  });
  return photoTimeline;
}

function photoTotalSeconds() {
  return photoTimeline.length ? photoTimeline[photoTimeline.length - 1].end : 0;
}

/** 그 시각에 보여야 할 사진으로 갈아 끼운다. */
function updatePhotoFrame(time) {
  const img = $("#player-img");
  if (!img || !photoTimeline.length) return;
  let pick = photoTimeline[photoTimeline.length - 1];
  for (const row of photoTimeline) {
    if (time < row.end) { pick = row; break; }
  }
  if (pick.index === shownPhotoIndex) return;
  shownPhotoIndex = pick.index;
  img.src = `/media/project/${encodeURIComponent(project.id)}/image/${pick.index}`;
}

/** 소리가 없는 사진 영상의 시계. 길이만 같은 무음 wav 를 만들어 <video> 에 물린다.
 *
 *  이렇게 하는 이유: 재생 위치를 읽는 곳이 화면 곳곳에 열두 군데가 넘는다.
 *  가짜 시계를 따로 만들면 그 열두 곳을 전부 고쳐야 하고, 한 곳만 빠뜨려도
 *  "재생은 되는데 자막만 안 따라오는" 상태가 된다. */
function silentClockSrc(seconds) {
  const rate = 8000;                                   // 브라우저가 받아 주는 가장 낮은 축
  const frames = Math.max(1, Math.ceil(seconds * rate));
  const buf = new ArrayBuffer(44 + frames);
  const view = new DataView(buf);
  const ascii = (offset, text) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
  ascii(0, "RIFF"); view.setUint32(4, 36 + frames, true); ascii(8, "WAVE");
  ascii(12, "fmt "); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);      // PCM
  view.setUint16(22, 1, true);      // 모노
  view.setUint32(24, rate, true);
  view.setUint32(28, rate, true);   // 초당 바이트
  view.setUint16(32, 1, true);      // 한 칸 크기
  view.setUint16(34, 8, true);      // 8비트
  ascii(36, "data"); view.setUint32(40, frames, true);
  new Uint8Array(buf, 44).fill(128);                   // 8비트 무음은 128이다 (0이 아니다)
  if (silentClockUrl) URL.revokeObjectURL(silentClockUrl);
  silentClockUrl = URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
  return silentClockUrl;
}

// ── 사진 목록 화면 ────────────────────────────────────────
function renderPhotoPanel() {
  const grp = $("#grp-photos");
  const list = $("#photo-list");
  if (!grp || !list) return;

  grp.hidden = !hasImages() && !hasOwnAudio();
  if (grp.hidden) return;

  const images = projectImages();
  const resolved = photoTimeline;
  const total = photoTotalSeconds();
  $("#photo-summary").textContent =
    `사진 ${images.length}장 · 전체 ${fmtTime(total)}` +
    (hasOwnAudio() ? " (길이는 음원에 맞춰집니다)" : "");

  const warn = $("#photo-warning");
  if (warn) {
    const message = photoMismatchWarning();
    warn.textContent = message ? `⚠ ${message}` : "";
    warn.hidden = !message;
  }

  list.innerHTML = "";
  images.forEach((img, index) => {
    const row = resolved.find((r) => r.index === index);
    const li = document.createElement("li");
    li.className = "photo-item";

    const thumb = document.createElement("img");
    thumb.className = "photo-thumb";
    thumb.loading = "lazy";
    thumb.alt = "";
    thumb.src = `/media/project/${encodeURIComponent(project.id)}/image/${index}`;

    const name = document.createElement("span");
    name.className = "photo-name";
    // 가사 줄에 짝지어져 있으면 파일 이름보다 **그 가사**를 보여 준다.
    // 어느 사진이 어느 줄에 붙었는지가 노래 영상에서 훨씬 중요한 정보다.
    const pairedSeg = img.seg_id ? segments().find((s) => s.id === img.seg_id) : null;
    if (pairedSeg) {
      name.textContent = `♪ ${pairedSeg.text || "(빈 줄)"}`;
      name.title = `이 사진은 「${pairedSeg.text}」 가 시작할 때 나옵니다\n${img.path}`;
    } else {
      name.textContent = String(img.path).split(/[\\/]/).pop();
      name.title = img.path;
    }

    const secs = document.createElement("input");
    secs.type = "number"; secs.min = "0.2"; secs.step = "0.1";
    secs.className = "photo-secs";
    secs.value = String(img.duration ?? 3);
    secs.disabled = !!img.seg_id;
    secs.title = img.seg_id ? "가사 줄에 맞춰져 있어 시간이 자동으로 정해집니다" : "이 사진이 보이는 시간(초)";
    secs.addEventListener("change", () => {
      snapshot();
      img.duration = Math.max(0.2, parseFloat(secs.value) || 3);
      afterPhotosChanged();
    });

    const when = document.createElement("span");
    when.className = "photo-when";
    when.textContent = row ? `${fmtTime(row.start)}~` : "";

    const up = document.createElement("button");
    up.className = "btn btn-tiny"; up.textContent = "▲"; up.title = "위로";
    up.disabled = index === 0;
    up.addEventListener("click", () => movePhoto(index, -1));

    const down = document.createElement("button");
    down.className = "btn btn-tiny"; down.textContent = "▼"; down.title = "아래로";
    down.disabled = index === images.length - 1;
    down.addEventListener("click", () => movePhoto(index, +1));

    const del = document.createElement("button");
    del.className = "btn btn-tiny"; del.textContent = "✕"; del.title = "이 사진 빼기";
    del.addEventListener("click", () => {
      snapshot();
      projectImages().splice(index, 1);
      afterPhotosChanged();
    });

    li.append(thumb, name, when, secs, up, down, del);
    list.appendChild(li);
  });
}

function movePhoto(index, step) {
  const images = projectImages();
  const target = index + step;
  if (target < 0 || target >= images.length) return;
  snapshot();
  const [moved] = images.splice(index, 1);
  images.splice(target, 0, moved);
  afterPhotosChanged();
}

/** 사진 목록이 바뀐 뒤에 해야 할 일을 한자리에 모은다.
 *  하나라도 빠뜨리면 "목록은 바뀌었는데 미리보기는 그대로"가 된다. */
function afterPhotosChanged() {
  refreshPhotoStage({ reloadClock: !hasOwnAudio() });
  renderPhotoPanel();
  applyFrameGuide();
  applyOverlayStyle();
  markDirty();
}

function wirePhotoPanel() {
  const add = $("#btn-add-photos");
  if (add) {
    add.addEventListener("click", async () => {
      try {
        const picked = await api("/api/system/pick-file?kind=images", { method: "POST" });
        if (picked.cancelled) return;
        snapshot();
        if (!project.images) project.images = [];
        const base = project.images.length;
        picked.paths.forEach((path, i) => {
          project.images.push({
            id: `i${Date.now().toString(36)}${(base + i).toString(36)}`,
            path, duration: 3.0, seg_id: null,
          });
        });
        if (!project.canvas) project.canvas = projectCanvas();
        afterPhotosChanged();
        toast(`사진 ${picked.paths.length}장을 넣었습니다.`);
      } catch (err) { toast(err.message, { error: true }); }
    });
  }

  const audio = $("#btn-photo-audio");
  if (audio) {
    audio.addEventListener("click", async () => {
      try {
        const picked = await api("/api/system/pick-file?kind=audio", { method: "POST" });
        if (picked.cancelled) return;
        snapshot();
        project.audio_path = picked.path;
        markDirty();
        await saveNow();
        renderProject();
        toast("음원을 넣었습니다. 재생하면 소리가 나옵니다.");
      } catch (err) { toast(err.message, { error: true }); }
    });
  }

  const applyEach = $("#btn-photo-apply-each");
  if (applyEach) {
    applyEach.addEventListener("click", () => {
      const secs = Math.max(0.2, parseFloat($("#photo-each-seconds").value) || 3);
      if (!hasImages()) { toast("사진이 없습니다.", { error: true }); return; }
      snapshot();
      for (const img of projectImages()) { if (!img.seg_id) img.duration = secs; }
      afterPhotosChanged();
      toast(`사진마다 ${secs}초로 맞췄습니다.`);
    });
  }

  // 노래 영상: 사진을 가사 줄에 순서대로 붙인다. 첫 사진↔첫 줄, 둘째↔둘째 …
  const pair = $("#btn-photo-pair");
  if (pair) {
    pair.addEventListener("click", () => {
      const segs = segments();
      if (!hasImages()) { toast("사진이 없습니다.", { error: true }); return; }
      if (!segs.length) { toast("가사(자막)가 없습니다. 먼저 가사를 넣어 주세요.", { error: true }); return; }
      snapshot();
      projectImages().forEach((img, i) => { img.seg_id = i < segs.length ? segs[i].id : null; });
      afterPhotosChanged();
      const paired = Math.min(projectImages().length, segs.length);
      toast(`사진 ${paired}장을 가사 줄에 맞췄습니다.`);
    });
  }

  const unpair = $("#btn-photo-unpair");
  if (unpair) {
    unpair.addEventListener("click", () => {
      if (!hasImages()) return;
      snapshot();
      for (const img of projectImages()) img.seg_id = null;
      afterPhotosChanged();
      toast("짝짓기를 풀었습니다. 이제 장당 시간대로 넘어갑니다.");
    });
  }
}

/** 사진·가사·음원의 길이가 안 맞을 때 무슨 일이 벌어지는지 한국어로 알려 준다.
 *
 *  내보내고 나서야 "뒤쪽 사진이 안 나왔다"는 것을 알면 다시 만들어야 한다.
 *  숫자와 함께 **결과가 어떻게 되는지**를 말해 준다. */
function photoMismatchWarning() {
  if (!project || !hasImages()) return null;

  const images = projectImages();
  const segs = segments();
  const paired = images.filter((img) => img.seg_id).length;
  const notes = [];

  if (paired > 0 && images.length !== segs.length) {
    if (images.length < segs.length) {
      notes.push(
        `사진이 ${images.length}장인데 가사는 ${segs.length}줄입니다. ` +
        `${images.length}번째 사진이 마지막 가사까지 계속 보입니다.`
      );
    } else {
      notes.push(
        `사진이 ${images.length}장인데 가사는 ${segs.length}줄입니다. ` +
        `짝을 못 찾은 뒤쪽 사진 ${images.length - segs.length}장은 각자 정해진 시간만큼 나옵니다.`
      );
    }
  }

  const total = photoTotalSeconds();
  const song = $("#player") && isFinite($("#player").duration) ? $("#player").duration : 0;
  if (hasOwnAudio() && song > 0.1 && total > 0.1) {
    const gap = song - total;
    if (gap > 0.5) {
      notes.push(`음원이 사진보다 ${gap.toFixed(1)}초 깁니다. 마지막 사진이 그만큼 더 보입니다.`);
    } else if (gap < -0.5) {
      notes.push(`사진이 음원보다 ${(-gap).toFixed(1)}초 깁니다. 뒷부분은 잘려 나갑니다.`);
    }
  }

  return notes.length ? notes.join(" ") : null;
}

/** 사진 프로젝트의 미리보기를 지금 상태에 맞춘다 (사진 목록·자막·화면비가 바뀔 때). */
function refreshPhotoStage({ reloadClock = false } = {}) {
  const img = $("#player-img");
  const player = $("#player");
  if (!img || !player) return;

  if (!hasImages()) {
    img.hidden = true;
    img.removeAttribute("src");
    photoTimeline = [];
    shownPhotoIndex = -1;
    renderPhotoPanel();
    return;
  }

  rebuildPhotoTimeline();
  img.hidden = false;
  shownPhotoIndex = -1;
  updatePhotoFrame(player.currentTime || 0);
  renderPhotoPanel();

  // 소리가 없으면 사진 길이만큼의 무음을 시계로 쓴다. 사진을 더하거나 시간을 바꾸면
  // 길이가 달라지므로 다시 만든다.
  if (!hasOwnAudio() && reloadClock) {
    player.src = silentClockSrc(photoTotalSeconds());
    player.load();
  }
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
        <li>대본이 있다면 상단 <b>[나레이션 작업]</b>에서 나레이션과 자막을 한 번에 만듭니다.</li>
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
  // 강제정렬이 짝을 못 찾아 **시각을 짐작한 줄**. 사용자가 그 줄만 고치면 되도록 표시한다.
  // 표시가 없으면 "완전 자동"이라고 믿게 되는데, 그 줄의 시각은 실제로 부정확하다.
  if (seg.guessed) li.classList.add("is-guessed");

  // 번호
  const no = document.createElement("span");
  no.className = "seg-no";
  no.textContent = index + 1;
  if (seg.guessed) no.title = "시각을 짐작한 줄입니다. [두드려 맞추기]로 고쳐 주세요.";

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

  // 대본 모드에서는 문장마다 목소리·속도·뒤 쉼을 따로 정할 수 있다 (CapCut이 못 하는 부분)
  if (project.mode === "script") li.appendChild(buildTtsControls(seg));

  updateRowMeta(li, seg);
  return li;
}

/** 문장 하나의 나레이션 개별 설정 줄. */
function buildTtsControls(seg) {
  seg.tts = seg.tts || {};
  const wrap = document.createElement("div");
  wrap.className = "seg-tts";

  const label = (text) => {
    const s = document.createElement("span");
    s.className = "tt-label"; s.textContent = text;
    return s;
  };

  // 목소리 — 비워 두면 전체 설정을 따른다
  const voice = document.createElement("select");
  voice.className = "tt-voice";
  voice.title = "이 문장만 다른 목소리로 읽게 합니다. 대화체 콘텐츠에 유용합니다.";
  const auto = document.createElement("option");
  auto.value = ""; auto.textContent = "전체 설정 따름";
  voice.appendChild(auto);
  for (const v of voices.filter((x) => x.speaks_korean)) {
    const opt = document.createElement("option");
    opt.value = v.id; opt.textContent = v.label;
    voice.appendChild(opt);
  }
  voice.value = seg.tts.voice || "";
  voice.addEventListener("change", () => {
    seg.tts.voice = voice.value || undefined;
    markDirty();
  });

  // 속도 — 전체 속도에 더해지는 값
  const rate = document.createElement("input");
  rate.type = "number"; rate.className = "tt-num";
  rate.min = "-50"; rate.max = "50"; rate.step = "5";
  rate.value = parseInt(String(seg.tts.rate || "+0%"), 10) || 0;
  rate.title = "이 문장만 더 느리게(-) 또는 빠르게(+) 읽습니다. 단위는 %";
  rate.addEventListener("change", () => {
    const v = clamp(parseInt(rate.value, 10) || 0, -50, 50);
    rate.value = v;
    seg.tts.rate = `${v >= 0 ? "+" : ""}${v}%`;
    markDirty();
  });

  // 뒤 쉼 — 이 문장이 끝난 뒤 얼마나 쉴지
  const gap = document.createElement("input");
  gap.type = "number"; gap.className = "tt-num";
  gap.min = "0"; gap.max = "5"; gap.step = "0.1";
  gap.placeholder = String(project.narration?.gap ?? 0.3);
  gap.value = seg.tts.gap ?? "";
  gap.title = "이 문장 뒤에만 따로 쉬는 시간(초). 비워 두면 전체 설정을 따릅니다.";
  gap.addEventListener("change", () => {
    const v = gap.value === "" ? undefined : clamp(parseFloat(gap.value) || 0, 0, 5);
    seg.tts.gap = v;
    markDirty();
  });

  // 이 문장만 듣기
  const play = document.createElement("button");
  play.className = "btn tt-play"; play.textContent = "🔊 듣기";
  play.title = "이 문장을 지금 설정한 목소리·속도로 들어 봅니다";
  play.addEventListener("click", async () => {
    const text = (seg.text || "").trim();
    if (!text) { toast("읽을 내용이 없습니다.", { error: true }); return; }
    await previewSentence(seg, play);
  });

  // 이 문장만 다시 만들기 (F-43) — 음성이 이미 있는 문장에만 보여 준다
  const regen = document.createElement("button");
  regen.className = "btn tt-regen";
  regen.textContent = "↻ 다시 만들기";
  regen.title = "글이나 설정을 고친 뒤 누르면 이 문장만 다시 만들고, 뒤쪽 자막 시각이 자동으로 밀립니다";
  regen.addEventListener("click", () => regenerateSentence(seg.id));

  wrap.append(label("목소리"), voice, label("속도"), rate, label("뒤 쉼"), gap, play);
  if (seg.tts.audio) wrap.appendChild(regen);
  return wrap;
}

async function previewSentence(seg, button) {
  const original = button.textContent;
  button.textContent = "만드는 중…"; button.disabled = true;
  try {
    const res = await fetch("/api/tts/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice: seg.tts?.voice || project.narration.voice,
        text: seg.text.slice(0, 200),
        rate: seg.tts?.rate || project.narration.global_rate || "+0%",
        pitch: project.narration.global_pitch || "+0Hz",
      }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `미리듣기 실패 (${res.status})`);
    }
    const measured = res.headers.get("X-Audio-Duration");
    const blob = await res.blob();
    if (previewAudio) { previewAudio.pause(); URL.revokeObjectURL(previewAudio.src); }
    previewAudio = new Audio(URL.createObjectURL(blob));
    previewAudio.play();
    if (measured) toast(`이 문장은 ${parseFloat(measured).toFixed(1)}초 걸립니다.`);
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    button.textContent = original; button.disabled = false;
  }
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
  // 0.1초 격자에 맞추지 않고 정확히 0.1초만 움직인다.
  // 음성인식이 만든 1.54초에서 ▶를 누르면 1.64초가 되어야지 1.6초가 되면 안 된다.
  seg[key] = Math.max(0, Math.round((seg[key] + delta) * 1000) / 1000);
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
    // 목록의 읽기 속도 색과 같은 기준을 쓴다 (노랑 = 빠름, 빨강 = 너무 빠름)
    const speed = cps(seg);
    if (speed > 11) clip.classList.add("is-toofast");
    else if (speed > 8.5) clip.classList.add("is-warn");
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

/** 타임라인을 다시 그린 뒤에는 파형과 구간 반복 표시도 함께 맞춰 준다. */
function renderTimelineAll() {
  renderTimeline();
  renderFxTrack();
  drawWaveform();
  renderABRegion();
}

// ══ 화면 효과 띠 (사용자가 구간을 정해서 건다) ═══════════════
//
// 관통 원칙: **아무 효과도 미리 넣지 않는다.** 사용자가 막대를 놓아야만 생긴다.
// 저장 구조와 필터는 서버의 app/core/effects.py 가 단일 출처이고, 여기는 그 목록을
// 그리고 고치기만 한다. 세기 값이나 배율 같은 것을 화면에 두 벌 두지 않는다.

let fxKinds = [];        // 서버가 알려 준 효과 종류 목록
let fxSelectedId = null; // 지금 고른 막대

function fxList() {
  if (!project) return [];
  if (!Array.isArray(project.effects)) project.effects = [];
  return project.effects;
}

async function loadFxKinds() {
  try {
    const data = await api("/api/system/effect-kinds");
    fxKinds = data.kinds || [];
  } catch {
    fxKinds = [];   // 목록을 못 받아도 나머지 화면은 그대로 동작해야 한다
  }
  renderFxKindButtons();
}

function renderFxKindButtons() {
  const box = $("#fx-kinds");
  if (!box) return;
  box.innerHTML = "";
  if (!fxKinds.length) {
    box.innerHTML = '<p class="hint">효과 목록을 불러오지 못했습니다. F5로 새로고침해 주세요.</p>';
    return;
  }
  for (const kind of fxKinds) {
    const btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = `＋ ${kind.label}`;
    btn.title = kind.hint || "";
    btn.addEventListener("click", () => addFxBar(kind.kind));
    box.appendChild(btn);
  }
}

/** 지금 재생 위치에 막대를 하나 놓는다. 기본 길이는 3초. */
function addFxBar(kind) {
  if (!project) { toast("먼저 영상을 열어 주세요.", { error: true }); return; }
  const total = totalDuration() || 0;
  const now = Math.round(($("#player").currentTime || 0) * 10) / 10;
  const start = clamp(now, 0, Math.max(0, total - 0.5));
  const end = total > 0 ? Math.min(total, start + 3) : start + 3;
  if (end - start < 0.2) {
    toast("영상 끝이라 효과를 놓을 자리가 없습니다. 재생 위치를 앞으로 옮겨 주세요.", { error: true });
    return;
  }
  snapshot();
  // id 는 서버가 저장할 때 다시 매긴다. 여기서는 화면에서 고르기 위한 임시 이름이다.
  const id = `fx-${Date.now()}`;
  fxList().push({ id, kind, start, end, strength: "medium", params: fxDefaults(kind) });
  fxSelectedId = id;
  renderTimelineAll(); syncFxPanel(); markDirty();
  const label = (fxKinds.find((k) => k.kind === kind) || {}).label || kind;
  toast(`${label}를 ${fmtTime(start)}부터 ${fmtTime(end)}까지 넣었습니다. 막대를 끌어 옮길 수 있습니다.`);
}

function renderFxTrack() {
  const track = $("#tl-fx-track");
  if (!track) return;
  track.innerHTML = "";
  const bars = fxList();
  if (!bars.length) {
    const empty = document.createElement("div");
    empty.className = "tl-empty";
    empty.textContent = "화면 효과 자리입니다. 왼쪽 [화면 효과]에서 고르면 여기에 막대로 놓입니다.";
    track.appendChild(empty);
    return;
  }
  for (const bar of bars) {
    const el = document.createElement("div");
    el.className = "tl-fx";
    el.dataset.id = bar.id;
    if (bar.id === fxSelectedId) el.classList.add("is-active");
    el.style.left = bar.start * pxPerSec + "px";
    el.style.width = Math.max(14, (bar.end - bar.start) * pxPerSec) + "px";
    const kind = fxKinds.find((k) => k.kind === bar.kind) || {};
    const strength = { low: "약하게", medium: "보통", high: "많이" }[bar.strength] || bar.strength;
    el.title = `${kind.label || bar.kind} · ${strength}\n${fmtTime(bar.start)} → ${fmtTime(bar.end)}\n`
             + "끌어서 옮기고, 양 끝을 끌어 길이를 바꿉니다.";

    const label = document.createElement("span");
    label.textContent = kind.label || bar.kind;
    el.appendChild(label);

    const gl = document.createElement("div"); gl.className = "grip grip-l";
    const gr = document.createElement("div"); gr.className = "grip grip-r";
    el.append(gl, gr);

    el.addEventListener("mousedown", (e) => startFxDrag(e, bar, el));
    el.addEventListener("click", (e) => { e.stopPropagation(); fxSelectedId = bar.id; renderFxTrack(); syncFxPanel(); });
    track.appendChild(el);
  }
}

/** 막대를 끌어 옮기거나 길이를 바꾼다 (자막 막대와 같은 규칙). */
function startFxDrag(e, bar, el) {
  e.preventDefault();
  const mode = e.target.classList.contains("grip-l") ? "left"
             : e.target.classList.contains("grip-r") ? "right" : "move";
  const startX = e.clientX;
  const orig = { start: bar.start, end: bar.end };
  const total = totalDuration() || Infinity;
  let moved = false;

  const onMove = (ev) => {
    const deltaSec = (ev.clientX - startX) / pxPerSec;
    if (Math.abs(ev.clientX - startX) > 2) moved = true;
    if (mode === "move") {
      const span = orig.end - orig.start;
      let next = Math.round((orig.start + deltaSec) * 10) / 10;
      next = clamp(next, 0, Math.max(0, total - span));
      bar.start = next; bar.end = next + span;
    } else if (mode === "left") {
      bar.start = clamp(Math.round((orig.start + deltaSec) * 10) / 10, 0, orig.end - 0.2);
    } else {
      bar.end = clamp(Math.round((orig.end + deltaSec) * 10) / 10, orig.start + 0.2, total);
    }
    el.style.left = bar.start * pxPerSec + "px";
    el.style.width = Math.max(14, (bar.end - bar.start) * pxPerSec) + "px";
  };

  const onUp = () => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    if (!moved) return;
    // 자막 막대와 같은 방식 — 되돌림점은 **바꾸기 전** 값으로 남긴다
    const after = { start: bar.start, end: bar.end };
    bar.start = orig.start; bar.end = orig.end;
    snapshot();
    bar.start = after.start; bar.end = after.end;
    fxSelectedId = bar.id;
    renderTimelineAll(); syncFxPanel(); markDirty();
  };

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

/** 고른 막대의 값을 패널에 맞춘다. */
function syncFxPanel() {
  const box = $("#fx-selected");
  const bars = fxList();
  const bar = bars.find((b) => b.id === fxSelectedId) || null;
  if (box) box.hidden = !bar;

  const warn = $("#fx-slow-warn");
  if (warn) warn.hidden = bars.length === 0;

  if (!bar) return;
  const kind = fxKinds.find((k) => k.kind === bar.kind) || {};
  const name = $("#fx-sel-name");
  if (name) name.textContent = kind.label || bar.kind;
  const startBox = $("#fx-start"), endBox = $("#fx-end");
  if (startBox) startBox.value = bar.start;
  if (endBox) endBox.value = bar.end;
  $$(".fx-strength").forEach((b) => b.classList.toggle("is-active", b.dataset.strength === bar.strength));
  renderFxParams(bar, kind);
}

/** 효과의 기본값. 서버가 알려 준 설명서에서 가져온다. */
function fxDefaults(kind) {
  const spec = fxKinds.find((k) => k.kind === kind);
  const out = {};
  for (const p of (spec && spec.params) || []) out[p.key] = p.default;
  return out;
}

/** 고른 막대의 값 슬라이더를 그린다.
 *
 * 효과마다 값이 다르므로 화면에 미리 만들어 둘 수 없다. 서버가 준 설명서
 * (이름·최소·최대·기본값)만 보고 그리므로, 새 효과에 값을 붙여도 여기를 고칠 일이 없다. */
function renderFxParams(bar, kind) {
  const box = $("#fx-params");
  if (!box) return;
  const specs = (kind && kind.params) || [];
  box.hidden = specs.length === 0;
  box.innerHTML = "";
  for (const spec of specs) {
    const now = bar.params && bar.params[spec.key] != null ? bar.params[spec.key] : spec.default;
    const row = document.createElement("label");
    row.className = "fx-param";

    const head = document.createElement("span");
    head.className = "fx-param-head";
    const title = document.createElement("span");
    title.textContent = spec.label;
    const shown = document.createElement("b");
    shown.textContent = `${now}${spec.suffix || ""}`;
    head.append(title, shown);

    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = spec.min;
    slider.max = spec.max;
    slider.step = spec.step || 1;
    slider.value = now;
    slider.addEventListener("input", () => {
      shown.textContent = `${slider.value}${spec.suffix || ""}`;
    });
    slider.addEventListener("change", () => {
      const live = fxList().find((b) => b.id === fxSelectedId);
      if (!live) return;
      snapshot();
      live.params = { ...(live.params || {}), [spec.key]: parseFloat(slider.value) };
      markDirty();
    });

    row.append(head, slider);
    box.append(row);
  }
}

function wireFxPanel() {
  for (const [id, key] of [["#fx-start", "start"], ["#fx-end", "end"]]) {
    const box = $(id);
    if (!box) continue;
    box.addEventListener("change", () => {
      const bar = fxList().find((b) => b.id === fxSelectedId);
      if (!bar) return;
      const value = Math.round((parseFloat(box.value) || 0) * 10) / 10;
      snapshot();
      if (key === "start") bar.start = clamp(value, 0, bar.end - 0.2);
      else bar.end = Math.max(bar.start + 0.2, value);
      renderTimelineAll(); syncFxPanel(); markDirty();
    });
  }

  $$(".fx-strength").forEach((btn) => {
    btn.addEventListener("click", () => {
      const bar = fxList().find((b) => b.id === fxSelectedId);
      if (!bar) return;
      snapshot();
      bar.strength = btn.dataset.strength;
      renderTimelineAll(); syncFxPanel(); markDirty();
    });
  });

  const del = $("#fx-delete");
  if (del) del.addEventListener("click", () => {
    const bars = fxList();
    const at = bars.findIndex((b) => b.id === fxSelectedId);
    if (at < 0) return;
    snapshot();
    bars.splice(at, 1);
    fxSelectedId = null;
    renderTimelineAll(); syncFxPanel(); markDirty();
    toast("효과 막대를 지웠습니다.");
  });

  loadFxKinds();
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
  renderTimelineAll();
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

  // 자막마다 길이가 다르므로 넘침 여부도 자막이 바뀔 때마다 다시 본다
  refreshSubtitleFitWarning();
}

/** 한 줄 최대 글자수에 맞춰 어절 단위로 줄을 나눈다 (F-11).
 *  서버의 app/core/subtitles.py wrap_text와 같은 규칙이어야 한다 —
 *  미리보기와 내보낸 결과가 달라지면 안 되기 때문이다. */
function wrapText(text) {
  const max = project?.style?.max_chars ?? 20;
  const lines = [];
  // 사용자가 직접 넣은 줄바꿈을 먼저 지킨다
  for (const paragraph of String(text).split("\n")) {
    let line = "";
    for (const w of paragraph.split(/\s+/).filter(Boolean)) {
      if (!line) { line = w; }
      else if ((line + " " + w).length <= max) { line += " " + w; }
      else { lines.push(line); line = w; }
    }
    lines.push(line);
  }
  while (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  // 줄 수가 넘쳐도 잘라내지 않는다. 글자를 감추면 사용자는 자막이 잘린 줄 모른 채
  // 내보내게 되고, 내보낸 파일에는 그 글자가 들어 있어 미리보기와 결과가 달라진다.
  // 너무 긴 자막은 [자막 검사]가 경고로 알려 준다.
  return lines.join("\n");
}

/** 미리보기 상자 안에서 **실제로 내보내지는 틀**이 차지하는 자리 (0~1 비율).
 *
 *  자막 위치는 "출력 틀의 몇 %"로 저장된다. 그런데 잘라내기를 쓰면 미리보기 상자는
 *  여전히 원본 전체를 보여 주므로, 상자를 기준으로 그리면 자막이 엉뚱한 곳에 보인다.
 *  (실측: 1280폭 영상을 왼쪽 끝 기준 9:16으로 자를 때 미리보기 640px vs 실제 202px)
 *  그래서 화면에 그릴 때도, 마우스로 끌 때도 반드시 이 함수를 거친다.
 */
function outputFrameRect() {
  const dims = sourceDimensions();
  const conf = currentOutput();
  if (!dims || conf.aspect === "source") return { left: 0, top: 0, w: 1, h: 1 };

  const frame = resolveFraming(dims.w, dims.h, conf);
  // 여백 채우기는 미리보기 상자 자체가 출력 틀이다 (CSS 로 상자를 그 화면비로 만들어 둔다)
  if (frame.fit === "pad" || !frame.crop) return { left: 0, top: 0, w: 1, h: 1 };

  return {
    left: frame.crop.x / dims.w,
    top: frame.crop.y / dims.h,
    w: frame.crop.w / dims.w,
    h: frame.crop.h / dims.h,
  };
}

function applyOverlayStyle() {
  const overlay = $("#overlay");
  const st = project?.style;
  if (!st) return;

  const player = $("#player");
  const fr = outputFrameRect();
  // 글자 크기는 '출력 틀의 세로 픽셀' 기준이다 (style_map.to_ass_style 과 같은 규칙).
  // 잘라내면 출력 틀의 높이가 줄어들 수 있으므로 상자 높이가 아니라 틀 높이를 써야 한다.
  const height = (player.clientHeight || 360) * fr.h;
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

  // 저장된 값은 '출력 틀의 몇 %'다. 그것을 미리보기 상자의 몇 %인지로 옮겨 그린다.
  const [x, y] = resolvedPosition(st);
  overlay.style.left = `${(fr.left + fr.w * x / 100) * 100}%`;
  overlay.style.top = `${(fr.top + fr.h * y / 100) * 100}%`;
  // 자막이 넘칠 수 있는 폭도 출력 틀 기준이어야 한다. 그래야 좁은 세로 화면에서
  // 자막이 틀 밖으로 나가는 것이 미리보기에서 그대로 보인다.
  overlay.style.maxWidth = `${fr.w * 92}%`;

  refreshSubtitleFitWarning();
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
    // 화면에 그릴 때와 **똑같은 틀**을 써야 한다. 한쪽만 고치면 끌 때마다 자막이 튄다.
    const fr = outputFrameRect();
    const onMove = (ev) => {
      // 마우스가 가리킨 상자 안의 자리를 '출력 틀의 몇 %'로 되돌린다
      const bx = (ev.clientX - rect.left) / rect.width;
      const by = (ev.clientY - rect.top) / rect.height;
      const x = clamp(((bx - fr.left) / fr.w) * 100, 0, 100);
      const y = clamp(((by - fr.top) / fr.h) * 100, 0, 100);
      project.style.position = { mode: "custom", preset: project.style.position?.preset || "bottom", x: +x.toFixed(1), y: +y.toFixed(1) };
      overlay.style.left = `${(fr.left + fr.w * x / 100) * 100}%`;
      overlay.style.top = `${(fr.top + fr.h * y / 100) * 100}%`;
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

  // 프리셋을 바꾸면 위에서 색 값만 바뀌고 화면의 색 칩은 그대로 남는다. 함께 맞춰 준다.
  if (typeof refreshColorPicks === "function") refreshColorPicks();

  const [x, y] = resolvedPosition(st);
  set("#style-pos-x", x.toFixed(1));
  set("#style-pos-y", y.toFixed(1));

  const isCustom = st.position?.mode === "custom";
  $$(".pos-btn").forEach((b) => b.classList.toggle("is-active", !isCustom && b.dataset.pos === st.position?.preset));
  $$(".preset").forEach((c) => c.classList.toggle("is-active", c.dataset.key === st.preset));
}

// 화살표 한 번에 움직이는 양 (화면 대비 %). Shift를 함께 누르면 BIG 쪽을 쓴다.
const NUDGE_STEP = 1, NUDGE_STEP_BIG = 5;
const NUDGE_DIRS = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

/** 자막을 화살표 방향으로 조금씩 옮긴다 (F-B).
 *  위치 프리셋(위/가운데/아래)을 쓰고 있었더라도 지금 보이는 자리를 출발점으로 삼아
 *  custom 으로 넘어간다. 그래야 화면에서 보이던 위치가 갑자기 튀지 않는다. */
function nudgePosition(dir, big) {
  if (!project) return;
  const delta = NUDGE_DIRS[dir];
  if (!delta) return;
  const step = big ? NUDGE_STEP_BIG : NUDGE_STEP;
  const [cx, cy] = resolvedPosition(project.style);
  // 소수점 한 자리로 맞춘다. 이렇게 하지 않으면 0.1이 쌓여 88.00000000000001 같은 값이 저장된다.
  const round1 = (v) => Math.round(v * 10) / 10;
  const x = clamp(round1(cx + delta[0] * step), 0, 100);
  const y = clamp(round1(cy + delta[1] * step), 0, 100);
  if (x === round1(cx) && y === round1(cy)) return;  // 이미 가장자리면 되돌림점을 남기지 않는다

  snapshot();
  project.style.position = {
    mode: "custom",
    preset: project.style.position?.preset || "bottom",
    x, y,
  };
  syncStyleInputs(); applyOverlayStyle(); markDirty();
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

  // 화살표 미세 조정 (F-B)
  $$(".nudge-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => nudgePosition(btn.dataset.nudge, e.shiftKey));
  });
  // Shift를 누르고 있는 동안에는 가운데 글자가 5%로 바뀐다 — 몇 %씩 움직일지 눌러 보기 전에 안다
  for (const [event, big] of [["keydown", true], ["keyup", false]]) {
    document.addEventListener(event, (e) => {
      if (e.key !== "Shift") return;
      const el = $(".nudge-step");
      if (el) el.textContent = big ? "5%" : "1%";
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
  $("#btn-shorts").addEventListener("click", applyShortsPreset);
}

// 덕킹 세기 — 화면에 적는 값은 tests/ducking_test.py 로 **실제로 재서** 넣는다.
// 압축기는 나레이션이 큰지 작은지에 따라 눌리는 양이 달라지므로 "정확히 몇 %"를
// 약속할 수 없다. 그래서 단계로 주고, 각 단계가 대략 어디쯤인지만 정직하게 적는다.
const DUCK_HINTS = {
  weak:   "말할 때 원본이 대략 70% 크기가 됩니다. 현장 소리를 함께 들려주고 싶을 때.",
  normal: "말할 때 원본이 대략 37% 크기가 됩니다. 대부분 이걸로 충분합니다.",
  strong: "말할 때 원본이 대략 22% 크기가 됩니다. 나레이션이 확실히 들려야 할 때.",
};

/** 덕킹을 켰는지에 따라 세기 단추와 볼륨 칸의 상태를 맞춘다. */
function renderDuckUI() {
  const on = !!project?.narration?.ducking;
  const level = project?.narration?.duck_level || "normal";

  $("#duck-strength").hidden = !on;
  // 덕킹을 켜면 볼륨 값은 쓰이지 않는다 — 흐리게 만들어 눈으로 알린다
  $("#origvol-field").classList.toggle("is-muted", on);

  document.querySelectorAll(".duck-btn").forEach((btn) =>
    btn.classList.toggle("is-active", btn.dataset.level === level)
  );
  const hint = $("#duck-hint");
  if (hint) hint.textContent = DUCK_HINTS[level] || "";
}

// ══ 나레이션 패널 ══════════════════════════════════════════
async function renderNarrationPanel() {
  const n = project?.narration;
  if (n) {
    $("#tts-gap").value = n.gap ?? 0.3;
    $("#tts-origvol").value = n.original_audio_volume ?? 30;
    $("#tts-ducking").checked = !!n.ducking;
    renderDuckUI();
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
      // 견본 문장은 보내지 않는다 — 서버가 그 목소리의 **언어에 맞는** 문장을 고른다.
      // 한국어 문장을 고정으로 보내면 한국어를 못 읽는 목소리가 소리를 하나도 안 준다.
      body: JSON.stringify({
        voice: voiceId,
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
  $("#tts-ducking").addEventListener("change", (e) => {
    project.narration.ducking = e.target.checked;
    renderDuckUI(); markDirty();
  });
  document.querySelectorAll(".duck-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      project.narration.duck_level = btn.dataset.level;
      renderDuckUI(); markDirty();
    })
  );

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
  tap: "두드려 맞추기 중 — 문장이 시작될 때마다 스페이스바를 누르세요. 끝내려면 [두드려 맞추기]를 다시 누릅니다.",
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
// 시작 화면의 카드는 <div role="button"> 이므로 키보드로 누르는 길을 직접 열어 준다.
function wireCard(id, handler) {
  const el = $(id);
  if (!el) return;
  el.addEventListener("click", handler);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handler(); }
  });
}

function wireStartScreen() {
  const pick = async () => {
    try {
      const result = await api("/api/system/pick-file", { method: "POST" });
      if (result.cancelled) return;
      await createProject({ name: result.name.replace(/\.[^.]+$/, ""), video_path: result.path, mode: "video" });
    } catch (err) { toast(err.message, { error: true }); }
  };

  // 사진으로 시작 — 여러 장을 한 번에 고른다. 고른 순서가 곧 영상에 나오는 순서다.
  const pickImages = async () => {
    try {
      const result = await api("/api/system/pick-file?kind=images", { method: "POST" });
      if (result.cancelled) return;
      const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      await createProject({
        name: `${stamp}_사진${result.paths.length}장`,
        image_paths: result.paths,
        mode: "video",
      });
    } catch (err) { toast(err.message, { error: true }); }
  };

  // 음원으로 시작 — mp3 하나로 시작하고 사진은 들어가서 추가한다.
  const pickAudio = async () => {
    try {
      const result = await api("/api/system/pick-file?kind=audio", { method: "POST" });
      if (result.cancelled) return;
      await createProject({
        name: result.name.replace(/\.[^.]+$/, ""),
        audio_path: result.path,
        mode: "video",
      });
    } catch (err) { toast(err.message, { error: true }); }
  };

  const zone = $("#drop-zone");
  wireCard("#drop-zone", pick);
  wireCard("#card-images", pickImages);
  wireCard("#card-audio", pickAudio);
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

  wireCard("#btn-start-script", () => {
    const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    createProject({ name: `${stamp}_나레이션`, video_path: null, mode: "script" });
  });
}

// ══ 작업 화면 연결 ═════════════════════════════════════════
function wireEditor() {
  $("#btn-home").addEventListener("click", async () => { await saveNow(); showStart(); });
  // 상태 글자를 눌러도 저장된다 (F-D). 사용자가 실제로 눌러 보려 했던 자리다.
  $("#save-state").addEventListener("click", () => saveNow({ flash: true }));
  $("#project-name").addEventListener("input", (e) => { project.name = e.target.value; markDirty(); });
  $("#mode-video").addEventListener("click", () => setMode("video"));
  $("#mode-script").addEventListener("click", () => setMode("script"));

  $("#script-input").addEventListener("input", (e) => { project.script = e.target.value; updateScriptStats(); markDirty(); });
  // 문장 나누기는 서버 규칙을 그대로 보여 준다 (화면과 결과가 달라지면 안 된다)
  $("#btn-split-script").addEventListener("click", previewScriptSplit);

  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
      $$(".tab-page").forEach((p) => { p.hidden = p.dataset.page !== btn.dataset.tab; });
    });
  });

  $("#stt-language").addEventListener("change", (e) => { project.stt.language = e.target.value; markDirty(); });
  $("#stt-model").addEventListener("change", (e) => { project.stt.model = e.target.value; markDirty(); });

  $("#btn-stt").addEventListener("click", runSTT);
  $("#btn-align").addEventListener("click", runAlign);
  $("#btn-export").addEventListener("click", openExportDialog);
  $("#btn-tts").addEventListener("click", runNarration);
  $("#btn-import-srt").addEventListener("click", importSubtitleFile);
  $("#btn-to-script").addEventListener("click", () => {
    if (!segments().length) { toast("옮길 자막이 없습니다.", { error: true }); return; }

    // 나레이션을 만들면 자막 시각이 **나레이션 길이 기준으로 전부 새로 계산된다.**
    // 공들여 맞춰 놓은 시각이 소리 없이 사라지므로 옮기기 전에 반드시 알린다.
    const ok = confirm(
      `자막 ${segments().length}개를 대본으로 옮깁니다.\n\n` +
      `⚠ 지금 자막에 맞춰 둔 시각은 나레이션을 만드는 순간 ` +
      `나레이션 길이에 맞춰 새로 계산됩니다. 지금 시각은 남지 않습니다.\n\n` +
      `목소리만 바꾸려는 것이라면 그대로 진행하시면 됩니다.\n계속할까요?`
    );
    if (!ok) return;

    snapshot();
    project.script = segments().map((s) => s.text).filter(Boolean).join("\n");
    $("#script-input").value = project.script;

    // 목소리를 바꾸려는 흐름이다 — 원본 소리가 들리면 두 목소리가 겹쳐 들린다.
    // 기본값 30%를 0%로 내리고, 무엇을 바꿨는지 알린다.
    let muted = false;
    if (project.narration && Number(project.narration.original_audio_volume) !== 0) {
      project.narration.original_audio_volume = 0;
      muted = true;
      renderNarrationPanel();
    }

    updateScriptStats(); setMode("script"); markDirty();
    toast(
      "자막을 대본으로 옮겼습니다." +
      (muted ? " 원본 소리는 0%로 내렸습니다 (목소리가 겹쳐 들리지 않도록)." : "")
    );
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

  $("#btn-autosplit").addEventListener("click", autoSplitBySilence);
  $("#btn-tapsync").addEventListener("click", toggleTapSync);
  $("#btn-ab").addEventListener("click", toggleAB);
  $("#chk-wave").addEventListener("change", drawWaveform);
  $("#chk-film").addEventListener("change", refreshFilmstrip);

  // ── 배경음악 ──────────────────────────────────────────
  $("#btn-pick-bgm").addEventListener("click", async () => {
    try {
      const result = await api("/api/system/pick-file?kind=audio", { method: "POST" });
      if (result.cancelled) return;
      project.bgm_path = result.path;
      renderBgm(); markDirty();
      toast("배경음악을 넣었습니다. 내보낼 때 영상에 깔립니다.");
    } catch (err) { toast(err.message, { error: true }); }
  });
  $("#btn-clear-bgm").addEventListener("click", () => {
    project.bgm_path = null;
    renderBgm(); markDirty();
  });
  $("#bgm-volume").addEventListener("change", (e) => {
    const v = parseInt(e.target.value, 10);
    project.bgm_volume = isNaN(v) ? 20 : Math.max(0, Math.min(100, v));
    e.target.value = project.bgm_volume;
    markDirty();
  });

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
    updatePhotoFrame(player.currentTime);
    enforceABLoop(player);
    // 여백 채우기의 흐린 배경이 본 영상과 같은 장면을 보이도록 따라가게 한다
    if (currentOutput().fit === "pad" && currentOutput().pad_blur) syncBlurBackground(true);
  });
  player.addEventListener("loadedmetadata", () => {
    $("#time-total").textContent = fmtTime(player.duration);
    // 영상 크기를 이제야 알 수 있다. 화면비 틀을 먼저 그려야 자막 위치를 그 틀 기준으로
    // 계산할 수 있으므로 순서를 지킨다.
    syncAspectInputs(); applyFrameGuide();
    applyOverlayStyle(); zoomFit();
  });
  player.addEventListener("error", () => {
    if (player.getAttribute("src")) toast("영상을 재생할 수 없습니다. 파일이 옮겨졌거나 지원하지 않는 형식일 수 있습니다.", { error: true });
  });

  // 사진이 바뀌면 그림 크기도 바뀐다. 화면비 틀과 자막 크기는 그 크기를 기준으로
  // 계산하므로, 사진이 실제로 그려진 뒤에 다시 그려야 자리가 맞는다.
  const stageImg = $("#player-img");
  if (stageImg) {
    stageImg.addEventListener("load", () => {
      applyFrameGuide();
      applyOverlayStyle();
      if (currentOutput().fit === "pad" && currentOutput().pad_blur) syncBlurBackground(true);
    });
    stageImg.addEventListener("error", () => {
      if (stageImg.getAttribute("src")) {
        toast("사진을 열지 못했습니다. 파일이 옮겨졌거나 지워졌을 수 있습니다.", { error: true });
      }
    });
  }
  $("#btn-play").addEventListener("click", () => (player.paused ? player.play() : player.pause()));
  player.addEventListener("play", () => {
    $("#btn-play").textContent = "⏸";
    if (currentOutput().fit === "pad" && currentOutput().pad_blur) syncBlurBackground(true);
  });
  player.addEventListener("pause", () => {
    $("#btn-play").textContent = "▶";
    const bg = $("#player-bg");
    if (bg && !bg.hidden) bg.pause();
  });
  player.addEventListener("seeked", () => {
    const bg = $("#player-bg");
    if (bg && !bg.hidden) bg.currentTime = player.currentTime;
  });
  $("#playback-rate").addEventListener("change", (e) => { player.playbackRate = parseFloat(e.target.value); });
  $("#btn-prev-seg").addEventListener("click", () => stepSegment(-1));
  $("#btn-next-seg").addEventListener("click", () => stepSegment(+1));
  window.addEventListener("resize", () => { applyOverlayStyle(); });

  wireSplitters();
  wireProgressBox();
  wireExportDialog();
  wireOverlayDrag();
  wireStylePanel();
  wirePhotoPanel();
  wireAspectPanel();
  wireFxPanel();
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
    // 저장이 끝나기 전에 "저장했습니다"라고 알리면 거짓말이 된다. 단추와 같은 경로를 쓴다.
    if (e.ctrlKey && e.key.toLowerCase() === "s") { e.preventDefault(); saveNow({ flash: true }); return; }

    if (typing) return;

    // 두드려 맞추기 중에는 스페이스바가 '지금 이 문장 시작' 표시로 쓰인다
    if (e.key === " " && tapSyncOn) { e.preventDefault(); tapMark(); return; }

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

// ══ 내 대본에 시간 붙이기 (강제정렬) ═══════════════════════
async function runAlign() {
  if (!project?.video_path && !project?.audio_path) {
    toast("먼저 말소리가 든 영상이나 음성 파일을 불러와 주세요.", { error: true });
    return;
  }
  const script = ($("#align-script").value || "").trim();
  if (!script) {
    toast("영상에서 말하는 내용을 붙여넣어 주세요.", { error: true });
    $("#align-script").focus();
    return;
  }
  if (segments().length && !confirm(
    `이미 자막 ${segments().length}개가 있습니다.\n시간을 붙이면 지금 자막을 모두 덮어씁니다.\n\n계속할까요?`)) {
    return;
  }

  const result = await runJob("대본에 시간을 붙이고 있습니다", () =>
    api(`/api/projects/${encodeURIComponent(project.id)}/align`, {
      method: "POST",
      body: JSON.stringify({
        script,
        language: project.stt.language,
        model: project.stt.model,
        max_chars: project.style.max_chars,
        max_lines: project.style.max_lines,
      }),
    })
  );
  if (!result) return;

  snapshot();
  project.segments = result.segments || [];
  renderAll();
  clearTimeout(saveTimer);
  await saveNow();

  const guessed = result.guessed || 0;
  if (guessed) {
    toast(
      `자막 ${result.total}개를 만들었습니다. 그중 ${guessed}개는 짝을 못 찾아 ` +
      `시각을 짐작했습니다 — 목록에서 노란 표시가 된 줄을 [두드려 맞추기]로 고쳐 주세요.`
    );
  } else {
    toast(`자막 ${result.total}개를 만들었습니다. 모든 줄이 잘 맞았습니다.`);
  }
}

// ══ 자막 자동 생성 (F-10) ══════════════════════════════════
async function runSTT() {
  if (!project?.video_path) {
    toast("먼저 영상이나 음성 파일을 불러와 주세요.", { error: true });
    return;
  }
  if (segments().length && !confirm(
    `이미 자막 ${segments().length}개가 있습니다.\n새로 만들면 지금 자막을 모두 덮어씁니다.\n\n계속할까요?`)) {
    return;
  }

  const result = await runJob("자막을 만들고 있습니다", () =>
    api(`/api/projects/${encodeURIComponent(project.id)}/stt`, {
      method: "POST",
      body: JSON.stringify({
        language: project.stt.language,
        model: project.stt.model,
        max_chars: project.style.max_chars,
        max_lines: project.style.max_lines,
      }),
    })
  );
  if (!result) return;

  snapshot();
  project.segments = result.segments || [];
  renderAll();
  clearTimeout(saveTimer);
  await saveNow();

  if (!project.segments.length) {
    toast("말소리를 찾지 못했습니다. 소리가 너무 작거나 음악만 있는 영상일 수 있습니다.", { error: true });
  } else {
    toast(`자막 ${project.segments.length}개를 만들었습니다. 이제 글자를 다듬어 보세요.`);
  }
}

// ══ 자막 파일 가져오기 (F-04) ══════════════════════════════
async function importSubtitleFile() {
  if (segments().length && !confirm(
    `이미 자막 ${segments().length}개가 있습니다.\n파일을 가져오면 지금 자막을 모두 덮어씁니다.\n\n계속할까요?`)) {
    return;
  }

  let picked;
  try {
    picked = await api("/api/system/pick-file?kind=subtitle", { method: "POST" });
  } catch (err) { toast(err.message, { error: true }); return; }
  if (picked.cancelled) return;

  try {
    const result = await api(`/api/projects/${encodeURIComponent(project.id)}/subtitles/import`, {
      method: "POST",
      body: JSON.stringify({ path: picked.path }),
    });
    await reloadProjectFromServer();
    toast(`자막 ${result.count}개를 가져왔습니다.`);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

// ══ 나레이션 만들기 (F-40, F-42, F-43) ═════════════════════
async function runNarration() {
  const script = $("#script-input").value.trim();
  if (!script) { toast("대본을 입력해 주세요.", { error: true }); return; }

  if (segments().length && !confirm(
    `이미 자막 ${segments().length}개가 있습니다.\n나레이션을 새로 만들면 지금 자막을 모두 덮어씁니다.\n\n계속할까요?`)) {
    return;
  }

  project.script = script;
  clearTimeout(saveTimer);
  await saveNow();

  const result = await runJob("나레이션을 만들고 있습니다", () =>
    api(`/api/projects/${encodeURIComponent(project.id)}/narration`, {
      method: "POST",
      body: JSON.stringify({ script }),
    })
  );
  if (!result) return;

  await reloadProjectFromServer();
  toast(`문장 ${result.count}개의 나레이션을 만들고 자막 시각을 맞췄습니다. (전체 ${result.duration}초)`);
  await refreshNarrationStatus();
}

/** 문장 하나만 다시 만든다 (F-43). 이후 자막 시각은 서버가 자동으로 다시 계산한다. */
async function regenerateSentence(segmentId) {
  clearTimeout(saveTimer);
  await saveNow();

  const result = await runJob("이 문장만 다시 만들고 있습니다", () =>
    api(`/api/projects/${encodeURIComponent(project.id)}/narration`, {
      method: "POST",
      body: JSON.stringify({ segment_id: segmentId }),
    })
  );
  if (!result) return;

  await reloadProjectFromServer();
  toast("이 문장을 다시 만들었습니다. 뒤쪽 자막 시각도 함께 옮겼습니다.");
  await refreshNarrationStatus();
}

/** 서버가 자막을 다시 써 주는 작업 뒤에는 프로젝트를 서버 기준으로 다시 읽는다. */
async function reloadProjectFromServer() {
  try {
    project = await api(`/api/projects/${encodeURIComponent(project.id)}`);
  } catch (err) {
    toast(`결과를 불러오지 못했습니다: ${err.message}`, { error: true });
    return;
  }
  undoStack = []; redoStack = [];
  renderAll();
  refreshUndoButtons();
  $("#save-state").textContent = "저장됨";
  refreshSaveTip();
}

/** 나레이션이 영상보다 길면 미리 알려 준다 (잘림 사고 예방). */
async function refreshNarrationStatus() {
  const box = $("#narr-status");
  if (!project) return;
  try {
    const info = await api(`/api/projects/${encodeURIComponent(project.id)}/narration/status`);
    if (info.warning) {
      box.textContent = `⚠ ${info.warning}`;
      box.className = "narr-status is-warn";
      box.hidden = false;
    } else if (info.ready) {
      box.textContent = `나레이션 ${info.narration_seconds}초 · 문장 ${info.voiced}개 준비됨`;
      box.className = "narr-status";
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  } catch (_) { box.hidden = true; }
}

async function previewScriptSplit() {
  const script = $("#script-input").value.trim();
  if (!script) { toast("대본이 비어 있습니다.", { error: true }); return; }
  try {
    const data = await api(`/api/projects/${encodeURIComponent(project.id)}/script/split`, {
      method: "POST",
      body: JSON.stringify({ script }),
    });
    alert(
      `문장 ${data.count}개로 나뉩니다. 예상 길이 약 ${data.estimated_seconds}초\n` +
      `(실제 길이는 음성을 만든 뒤 정확히 측정됩니다)\n\n` +
      data.sentences.map((s, i) => `${i + 1}. ${s}`).join("\n")
    );
  } catch (err) { toast(err.message, { error: true }); }
}

// ══ 내보내기 (F-03, F-50, F-54) ════════════════════════════
async function openExportDialog() {
  if (!project) return;
  const dialog = $("#export-dialog");
  $("#export-done").hidden = true;

  // 나레이션이 영상보다 길면 뒷부분이 잘린다. 내보내기 직전에 반드시 알린다 —
  // 나레이션을 만든 지 한참 뒤에 내보내는 경우가 많아서, 만들 때 한 번 알린 것으로는 부족하다.
  const warnBox = $("#export-warning");
  warnBox.hidden = true;
  exportWarning = null;
  try {
    const info = await api(`/api/projects/${encodeURIComponent(project.id)}/narration/status`);
    if (info.warning) {
      exportWarning = info.warning;
      warnBox.textContent = `⚠ ${info.warning}`;
      warnBox.hidden = false;
    }
  } catch (_) { /* 경고를 못 받아도 내보내기 자체는 막지 않는다 */ }

  // 사진·가사·음원의 길이가 안 맞으면 여기서도 알린다. 왼쪽 [사진] 칸에도 같은
  // 문구가 뜨지만, 내보내기 직전에 다시 보여 주지 않으면 그냥 지나친다.
  const photoNote = photoMismatchWarning();
  if (photoNote) {
    exportWarning = exportWarning ? `${exportWarning}\n${photoNote}` : photoNote;
    warnBox.textContent = `⚠ ${exportWarning}`;
    warnBox.hidden = false;
  }

  // 화면비를 바꿔 두었으면 어떤 크기로 나가는지 내보내기 직전에 한 번 더 알린다.
  // 설정 화면을 떠난 뒤 한참 있다 내보내는 경우가 많아 여기서 다시 보여 줘야 한다.
  const conf = currentOutput();
  const dims = sourceDimensions();
  const note = $("#export-aspect-note");
  if (note) {
    if (conf.aspect === "source" || !dims) {
      note.hidden = true;
    } else {
      const frame = resolveFraming(dims.w, dims.h, conf);
      const how = frame.fit === "pad"
        ? `원본 전체를 넣고 남는 곳은 ${conf.pad_blur ? "흐린 배경" : "검은색"}으로 채웁니다`
        : "가장자리를 잘라 냅니다";
      let text =
        `영상은 ${FR_ASPECT_LABELS[conf.aspect]} · ${frame.width}×${frame.height} 로 나갑니다 — ${how}.`;
      // 자막이 틀 밖으로 나가 있으면 내보내기 직전에 반드시 알린다 (그냥 두면 조용히 잘린다)
      const over = subtitleOverflow();
      if (over) {
        text += `\n⚠ 지금 자막이 틀 밖으로 약 ${over.sourcePixels}픽셀 넘쳐서 그만큼 잘립니다.`;
      }
      note.textContent = text;
      note.style.whiteSpace = "pre-line";
      note.hidden = false;
    }
  }

  const hasSegments = segments().length > 0;
  // 사진 프로젝트에는 원본 영상이 없지만 **사진이 그림이 되므로** 영상을 만들 수 있다.
  // 여기서 빼먹으면 사진 프로젝트에서 [자막 입힌 영상]이 회색으로 잠긴다.
  const hasVideo = !!project.video_path || hasImages();
  const hasNarration = !!(project.narration || {}).audio;

  for (const btn of $$(".export-opt")) {
    const kind = btn.dataset.kind;
    const needsVideo = kind === "burn" || kind === "preview" || kind === "narr_video";
    const needsNarration = kind === "narr_audio" || kind === "narr_video";
    const needsSegments = !needsNarration;

    let reason = "";
    if (needsSegments && !hasSegments) reason = "먼저 자막을 만들어 주세요.";
    else if (needsNarration && !hasNarration) reason = "먼저 [나레이션 작업]에서 나레이션을 만들어 주세요.";
    else if (needsVideo && !hasVideo) reason = "영상이 있어야 만들 수 있습니다.";

    btn.disabled = !!reason;
    btn.title = reason;
  }
  dialog.hidden = false;
}

async function doExport(kind) {
  const labels = {
    srt: "자막 파일(SRT)을 만들고 있습니다",
    vtt: "자막 파일(VTT)을 만들고 있습니다",
    preview: "10초 미리보기를 만들고 있습니다",
    burn: "자막을 새긴 영상을 만들고 있습니다",
    narr_audio: "나레이션 오디오를 만들고 있습니다",
    narr_video: "나레이션을 영상에 입히고 있습니다",
  };

  // 잘림 경고가 있는데 영상으로 내보내려 한다면 한 번 더 확인받는다
  if (exportWarning && (kind === "narr_video" || kind === "burn")) {
    if (!confirm(`${exportWarning}\n\n그래도 이대로 만들까요?`)) return;
  }

  clearTimeout(saveTimer);
  await saveNow();  // 서버가 최신 자막으로 만들도록 먼저 저장한다

  // 나레이션 관련 두 가지는 다른 주소를 쓴다
  const isNarration = kind === "narr_audio" || kind === "narr_video";
  const path = isNarration
    ? `/api/projects/${encodeURIComponent(project.id)}/narration/export`
    : `/api/projects/${encodeURIComponent(project.id)}/render`;
  const body = isNarration
    ? { kind: kind === "narr_audio" ? "audio" : "video", fmt: "mp3" }
    : { kind };

  const result = await runJob(labels[kind] || "내보내는 중입니다", () =>
    api(path, { method: "POST", body: JSON.stringify(body) })
  );
  if (!result) return;

  $("#export-done-name").textContent = `완성: ${result.name}`;
  $("#export-done").hidden = false;
  toast(`내보내기를 마쳤습니다: ${result.name}`);
}

function wireExportDialog() {
  $$(".export-opt").forEach((btn) => {
    btn.addEventListener("click", () => doExport(btn.dataset.kind));
  });
  $("#export-close").addEventListener("click", () => { $("#export-dialog").hidden = true; });
  $("#export-dialog").addEventListener("click", (e) => {
    if (e.target.id === "export-dialog") $("#export-dialog").hidden = true;
  });
  $("#btn-open-folder").addEventListener("click", async () => {
    try {
      await api("/api/system/open-folder", {
        method: "POST",
        body: JSON.stringify({ project_id: project.id, subdir: "out" }),
      });
    } catch (err) { toast(err.message, { error: true }); }
  });
}

// ══ 오래 걸리는 작업 진행률 ════════════════════════════════
let activeJobId = null;
let jobTimer = null;

/** 작업을 시작하고 끝날 때까지 진행률을 보여 준다.
 *  start()는 {job_id} 를 돌려주는 함수여야 한다.
 *  끝나면 서버가 돌려준 result 를 그대로 반환한다. */
async function runJob(label, start) {
  if (activeJobId) { toast("이미 진행 중인 작업이 있습니다. 끝나면 다시 시도해 주세요.", { error: true }); return null; }

  const box = $("#progress-box");
  $("#pg-label").textContent = label;
  $("#pg-message").textContent = "준비 중입니다…";
  $("#pg-percent").textContent = "0%";
  $("#pg-fill").style.width = "0%";
  box.hidden = false;

  let started;
  try {
    started = await start();
  } catch (err) {
    box.hidden = true;
    toast(err.message, { error: true });
    return null;
  }
  activeJobId = started.job_id;

  return new Promise((resolve) => {
    jobTimer = setInterval(async () => {
      let job;
      try {
        job = await api(`/api/jobs/${activeJobId}`);
      } catch (err) {
        finishJob();
        toast(`진행 상황을 확인하지 못했습니다: ${err.message}`, { error: true });
        resolve(null);
        return;
      }

      $("#pg-fill").style.width = `${job.percent}%`;
      $("#pg-percent").textContent = `${job.percent}%`;
      $("#pg-message").textContent = job.message;

      if (job.status === "done") {
        finishJob();
        resolve(job.result);
      } else if (job.status === "error") {
        finishJob();
        toast(job.error || "작업이 실패했습니다.", { error: true });
        resolve(null);
      } else if (job.status === "cancelled") {
        finishJob();
        toast("작업을 취소했습니다.");
        resolve(null);
      }
    }, 1000);
  });
}

function finishJob() {
  clearInterval(jobTimer);
  jobTimer = null;
  activeJobId = null;
  $("#progress-box").hidden = true;
}

function wireProgressBox() {
  $("#pg-cancel").addEventListener("click", async () => {
    if (!activeJobId) return;
    try {
      await api(`/api/jobs/${activeJobId}/cancel`, { method: "POST" });
      $("#pg-message").textContent = "취소하는 중입니다…";
    } catch (err) { toast(err.message, { error: true }); }
  });
}

// ══ 패널 크기 조절 ═════════════════════════════════════════
const LAYOUT_KEY = "moviefit.layout.v1";
// 영상 띠(36px)가 눈금 아래에 한 줄 더 들어가므로 기본 높이를 그만큼 키웠다.
const LAYOUT_DEFAULT = { left: 250, right: 300, bottom: 310, timeline: 134 };
// 영상 띠를 켤 때 이보다 낮으면 자막 막대가 들어갈 자리가 없다.
// (눈금 22 + 띠 36 = 58, 자막 막대 51 → 109. 여유를 두어 134)
const TIMELINE_MIN_WITH_FILM = 134;

function applyLayout(layout) {
  const root = $("#view-editor");
  root.style.setProperty("--left-w", `${layout.left}px`);
  root.style.setProperty("--right-w", `${layout.right}px`);
  root.style.setProperty("--bottom-h", `${layout.bottom}px`);
  root.style.setProperty("--timeline-h", `${layout.timeline}px`);
}

/** 영상 띠를 켤 때 타임라인이 너무 낮으면 자막 막대가 눌린다. 최소한만 넓혀 준다.
 *  예전에 쓰던 사람은 96px 로 저장해 두었기 때문에 이 보정이 없으면 트랙이 37px 로 눌린다. */
function ensureTimelineFitsFilm() {
  const layout = loadLayout();
  if (layout.timeline >= TIMELINE_MIN_WITH_FILM) return;
  layout.timeline = TIMELINE_MIN_WITH_FILM;
  applyLayout(layout);
  saveLayout(layout);
}

function loadLayout() {
  try {
    const saved = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "{}");
    return { ...LAYOUT_DEFAULT, ...saved };
  } catch (_) { return { ...LAYOUT_DEFAULT }; }
}

function saveLayout(layout) { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); }

function wireSplitters() {
  const layout = loadLayout();
  applyLayout(layout);

  /** 손잡이 하나를 끌 수 있게 만든다.
   *  axis "x"면 좌우 폭, "y"면 위아래 높이. sign은 끄는 방향과 값이 커지는 방향의 관계. */
  const makeDraggable = (sel, key, axis, sign, min, max) => {
    const handle = $(sel);
    if (!handle) return;

    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startPos = axis === "x" ? e.clientX : e.clientY;
      const startValue = loadLayout()[key];
      handle.classList.add("is-dragging");
      document.body.classList.add("is-resizing");

      const onMove = (ev) => {
        const now = axis === "x" ? ev.clientX : ev.clientY;
        const next = clamp(startValue + (now - startPos) * sign, min, max());
        const current = loadLayout();
        current[key] = Math.round(next);
        applyLayout(current);
        saveLayout(current);
      };
      const onUp = () => {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        handle.classList.remove("is-dragging");
        document.body.classList.remove("is-resizing");
        // 크기가 바뀌면 타임라인과 자막 미리보기를 다시 그려야 한다
        renderTimeline(); drawWaveform(); applyOverlayStyle();
      };
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    // 두 번 클릭하면 기본값으로 되돌린다
    handle.addEventListener("dblclick", () => {
      const current = loadLayout();
      current[key] = LAYOUT_DEFAULT[key];
      applyLayout(current); saveLayout(current);
      renderTimeline(); drawWaveform(); applyOverlayStyle();
      toast("기본 크기로 되돌렸습니다.");
    });

    // 키보드로도 조절할 수 있게 (손잡이에 초점을 두고 화살표)
    handle.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 40 : 10;
      let delta = 0;
      if (axis === "x" && e.key === "ArrowLeft") delta = -step;
      else if (axis === "x" && e.key === "ArrowRight") delta = step;
      else if (axis === "y" && e.key === "ArrowUp") delta = -step;
      else if (axis === "y" && e.key === "ArrowDown") delta = step;
      else return;
      e.preventDefault(); e.stopPropagation();
      const current = loadLayout();
      current[key] = Math.round(clamp(current[key] + delta * sign, min, max()));
      applyLayout(current); saveLayout(current);
      renderTimeline(); drawWaveform();
    });
  };

  makeDraggable("#split-left", "left", "x", +1, 160, () => window.innerWidth * 0.4);
  makeDraggable("#split-right", "right", "x", -1, 180, () => window.innerWidth * 0.45);
  makeDraggable("#split-bottom", "bottom", "y", -1, 140, () => window.innerHeight * 0.75);
  makeDraggable("#split-timeline", "timeline", "y", +1, 60, () => loadLayout().bottom - 120);
}

// ══ 소리 파형 ══════════════════════════════════════════════
/** 배경음악 칸 — 영상이 있는 프로젝트에서만 쓸 수 있다.
 *  사진만 있는 프로젝트의 '음원'은 영상 길이를 정하는 주인공이라 여기서 다루지 않는다. */
function renderBgm() {
  const box = $("#grp-bgm");
  if (!box) return;
  box.hidden = !project?.video_path;
  if (box.hidden) return;

  const path = project.bgm_path || "";
  $("#bgm-info").textContent = path || "아직 넣지 않았습니다.";
  $("#bgm-volume").value = project.bgm_volume ?? 20;
  $("#btn-clear-bgm").disabled = !path;
}

/** 타임라인의 영상 띠를 켜고 끈다. 영상이 없는 프로젝트에서는 아예 숨긴다. */
function refreshFilmstrip() {
  const img = $("#tl-film");
  const inner = $("#tl-inner");
  if (!img || !inner) return;

  const want = $("#chk-film")?.checked !== false;
  const has = !!project?.video_path;

  if (!want || !has) {
    img.hidden = true;
    img.removeAttribute("src");
    inner.classList.remove("has-film");
    return;
  }

  const src = `/media/project/${encodeURIComponent(project.id)}/filmstrip`;
  if (img.getAttribute("src") !== src) {
    // 그림을 만드는 데 몇 초 걸릴 수 있다. 다 받은 뒤에 보여야 빈 칸이 깜빡이지 않는다.
    img.hidden = true;
    inner.classList.remove("has-film");
    img.onload = () => {
      img.hidden = false; inner.classList.add("has-film");
      ensureTimelineFitsFilm();
      drawWaveform();  // 파형 자리가 36px 내려갔으므로 다시 그린다
    };
    img.onerror = () => { img.hidden = true; inner.classList.remove("has-film"); };
    img.src = src;
  } else {
    img.hidden = false;
    inner.classList.add("has-film");
    ensureTimelineFitsFilm();
    drawWaveform();
  }
}

async function loadWaveform() {
  if (!project?.video_path) { waveformPeaks = null; return; }
  try {
    const data = await api(`/api/audio/waveform/${encodeURIComponent(project.id)}?buckets=2000`);
    waveformPeaks = data.peaks;
    drawWaveform();
  } catch (_) {
    // 파형은 보조 기능이다. 못 그려도 나머지는 정상 동작해야 한다.
    waveformPeaks = null;
    drawWaveform();
  }
}

function drawWaveform() {
  const canvas = $("#tl-wave");
  if (!canvas) return;

  const show = $("#chk-wave")?.checked;
  if (!show || !waveformPeaks || !waveformPeaks.length) { canvas.hidden = true; return; }
  canvas.hidden = false;

  const total = totalDuration();
  const cssWidth = Math.max(600, total * pxPerSec);
  const cssHeight = Math.max(20, $("#tl-track").clientHeight || 60);

  // 고해상도 화면에서도 선명하게 그린다
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = cssWidth + "px";
  canvas.style.height = cssHeight + "px";
  canvas.width = Math.round(cssWidth * dpr);
  canvas.height = Math.round(cssHeight * dpr);

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);
  ctx.fillStyle = "#5EEAD4";

  const mid = cssHeight / 2;
  const n = waveformPeaks.length;
  const step = cssWidth / n;
  const barWidth = Math.max(1, step * 0.85);

  for (let i = 0; i < n; i++) {
    const h = Math.max(1, waveformPeaks[i] * (cssHeight * 0.92));
    ctx.fillRect(i * step, mid - h / 2, barWidth, h);
  }
}

// ══ 무음으로 자동 나누기 ═══════════════════════════════════
async function autoSplitBySilence() {
  if (!project?.video_path) { toast("영상이 있어야 소리를 분석할 수 있습니다.", { error: true }); return; }

  const btn = $("#btn-autosplit");
  const original = btn.innerHTML;
  btn.innerHTML = "분석 중…"; btn.disabled = true;
  try {
    const data = await api(`/api/audio/silence/${encodeURIComponent(project.id)}`);
    const regions = data.regions || [];
    if (!regions.length) { toast("말소리 구간을 찾지 못했습니다.", { error: true }); return; }

    const keepText = segments().length > 0 &&
      confirm(`말소리 구간 ${regions.length}개를 찾았습니다.\n\n` +
              `[확인] 기존 자막 글자를 순서대로 새 구간에 배치합니다.\n` +
              `[취소] 기존 자막을 지우고 빈 자막 ${regions.length}개를 만듭니다.`);

    snapshot();
    const oldTexts = segments().map((s) => s.text);
    project.segments = regions.map((r, i) => ({
      id: "s" + String(i + 1).padStart(3, "0"),
      start: Math.round(r.start * 10) / 10,
      end: Math.round(r.end * 10) / 10,
      text: keepText ? (oldTexts[i] || "") : "",
    }));
    renderAll(); markDirty();
    toast(`말소리 구간 ${regions.length}개로 자막을 나눴습니다.`);
  } catch (err) {
    toast(err.message, { error: true });
  } finally {
    btn.innerHTML = original; btn.disabled = false;
  }
}

// ══ 두드려 맞추기 (탭 싱크) ════════════════════════════════
function toggleTapSync() {
  tapSyncOn = !tapSyncOn;
  const btn = $("#btn-tapsync");
  btn.classList.toggle("is-on", tapSyncOn);
  if (tapSyncOn) {
    if (!segments().length) {
      toast("먼저 자막 글을 넣어 두세요. 나레이션 작업에서 [자막을 대본으로]의 반대로, 대본 문장을 자막으로 만들어 두면 편합니다.", { error: true });
      tapSyncOn = false; btn.classList.remove("is-on"); return;
    }
    selectedId = segments()[0].id;
    $("#player").play();
    setHelp("tap");
    toast("두드려 맞추기 시작 — 문장이 시작될 때마다 스페이스바를 누르세요. 다시 [두드려 맞추기]를 누르면 끝납니다.");
  } else {
    $("#player").pause();
    setHelp("idle");
    toast("두드려 맞추기를 끝냈습니다.");
  }
}

function tapMark() {
  const player = $("#player");
  const segs = segments();
  const i = Math.max(0, segIndex(selectedId));
  const seg = segs[i];
  if (!seg) { toggleTapSync(); return; }

  const now = Math.round(player.currentTime * 10) / 10;
  if (i === 0) snapshot();

  seg.start = now;
  // 앞 자막의 끝을 이번 시작점까지 늘린다
  if (i > 0) segs[i - 1].end = now;
  seg.end = Math.max(now + 0.5, seg.end);

  if (i < segs.length - 1) {
    selectedId = segs[i + 1].id;
    renderSegments($("#seg-search").value);
    renderTimeline();
    scrollToSegmentRow(selectedId);
  } else {
    seg.end = Math.max(now + 1, player.duration || now + 1);
    renderAll();
    toggleTapSync();
  }
  markDirty();
}

// ══ A-B 구간 반복 ══════════════════════════════════════════
function toggleAB() {
  const player = $("#player");
  const now = player.currentTime || 0;
  const btn = $("#btn-ab");

  // 단추 글자에 'A', 'B' 같은 말을 쓰지 않는다. 지금 눌러야 할 일을 그대로 적는다.
  if (!abLoop) {
    abLoop = { start: now };
    btn.textContent = "끝 지점 찍기";
    btn.title = `시작 ${fmtTime(now)} — 반복하고 싶은 구간의 끝에서 다시 누르세요.`;
    btn.classList.add("is-on");
    toast(`${fmtTime(now)} 를 시작으로 찍었습니다. 끝나는 곳에서 한 번 더 누르세요.`);
  } else if (abLoop.end === undefined) {
    if (now <= abLoop.start + 0.2) { toast("끝 지점은 시작보다 뒤여야 합니다.", { error: true }); return; }
    abLoop.end = now;
    btn.textContent = "반복 끄기";
    btn.title = `${fmtTime(abLoop.start)} ~ ${fmtTime(abLoop.end)} 구간을 되풀이하는 중입니다. 누르면 멈춥니다.`;
    toast(`${fmtTime(abLoop.start)} ~ ${fmtTime(abLoop.end)} 구간을 되풀이합니다.`);
  } else {
    abLoop = null;
    btn.textContent = "구간 반복";
    btn.title = "같은 구간을 되풀이해 들으며 자막을 맞출 때 씁니다. 시작에서 한 번, 끝에서 한 번 누르세요.";
    btn.classList.remove("is-on");
    toast("구간 되풀이를 껐습니다.");
  }
  renderABRegion();
}

function renderABRegion() {
  const el = $("#tl-ab");
  if (!abLoop || abLoop.end === undefined) { el.hidden = true; return; }
  el.hidden = false;
  el.style.left = abLoop.start * pxPerSec + "px";
  el.style.width = (abLoop.end - abLoop.start) * pxPerSec + "px";
}

function enforceABLoop(player) {
  if (abLoop && abLoop.end !== undefined && player.currentTime >= abLoop.end) {
    player.currentTime = abLoop.start;
  }
}

// ══ 출력 화면비 — 롱폼·숏폼 (F-A, F-C) ═════════════════════
//
// 아래 계산은 서버의 app/core/framing.py 와 **똑같은 답**을 내야 한다. 미리보기 틀은
// 마우스를 끄는 동안 즉시 다시 그려야 해서 서버에 물어볼 수 없기 때문에 같은 규칙을
// 여기에도 둔다. 두 곳이 어긋나지 않는지는 tests/phase4_test.py 가 실제로 대조한다.

const FR_ASPECTS = { "16:9": [16, 9], "9:16": [9, 16], "1:1": [1, 1] };
const FR_ASPECT_LABELS = {
  source: "원본 그대로", "16:9": "가로 16:9", "9:16": "세로 9:16", "1:1": "정사각 1:1",
};
const FR_DEFAULT = { aspect: "source", fit: "crop", focus_x: 50, focus_y: 50, pad_blur: true, zoom: 1 };
// 확대 한계. framing.py 의 ZOOM_MIN/ZOOM_MAX 와 같은 값이어야 한다.
const FR_ZOOM_MIN = 0.5, FR_ZOOM_MAX = 2.0;

// 0.5는 언제나 위로. 파이썬 쪽 _round() 와 같은 규칙이다 (파이썬 기본 round는 다르게 동작한다).
const frRound = (v) => Math.floor(v + 0.5);
const frEven = (v) => { const n = frRound(v); return Math.max(2, n - (n % 2)); };

function normalizeOutput(output) {
  const src = Object.assign({}, FR_DEFAULT, output || {});
  let aspect = String(src.aspect || "source");
  if (aspect !== "source" && !(aspect in FR_ASPECTS)) aspect = "source";
  let fit = String(src.fit || "crop");
  if (fit !== "crop" && fit !== "pad") fit = "crop";
  const pct = (v) => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? Math.round(clamp(n, 0, 100) * 100) / 100 : 50;
  };
  const zn = parseFloat(src.zoom);
  const zoom = Number.isFinite(zn)
    ? Math.round(clamp(zn, FR_ZOOM_MIN, FR_ZOOM_MAX) * 1000) / 1000
    : 1;
  return {
    aspect, fit,
    focus_x: pct(src.focus_x), focus_y: pct(src.focus_y),
    pad_blur: src.pad_blur !== false,
    zoom,
  };
}

/** 원본 크기와 설정으로 최종 출력 크기와 잘라낼 영역을 구한다 (framing.resolve 와 같은 계산). */
function resolveFraming(srcWidth, srcHeight, output) {
  const conf = normalizeOutput(output);
  const srcW = Math.trunc(srcWidth), srcH = Math.trunc(srcHeight);
  if (!(srcW > 0) || !(srcH > 0)) throw new Error("원본 영상 크기가 올바르지 않습니다.");

  const zoom = conf.zoom;
  const evenSrcW = frEven(srcW), evenSrcH = frEven(srcH);

  // 화면비도 안 바꾸고 확대도 안 하면 손댈 것이 없다 (옛 프로젝트가 여기로 온다).
  if (conf.aspect === "source" && zoom === 1) {
    return { width: evenSrcW, height: evenSrcH, changed: false,
             aspect: "source", fit: conf.fit, crop: null, zoom: 1, sharpness: 1 };
  }

  // "원본 그대로"에 확대만 거는 경우, 목표 화면비는 원본 화면비와 같다.
  let targetRatio;
  if (conf.aspect === "source") targetRatio = srcW / srcH;
  else { const [rw, rh] = FR_ASPECTS[conf.aspect]; targetRatio = rw / rh; }
  const sourceRatio = srcW / srcH;

  if (conf.fit === "crop") {
    // 확대 없이 잘라낼 때의 크기. 이것이 곧 출력 크기이며 확대해도 변하지 않는다.
    let baseW, baseH;
    if (sourceRatio > targetRatio) { baseH = srcH; baseW = srcH * targetRatio; }
    else { baseW = srcW; baseH = srcW / targetRatio; }
    const outW = frEven(baseW), outH = frEven(baseH);

    // 원본에서 실제로 보이는 영역 = 출력 크기 ÷ 확대.
    const visW = frEven(outW / zoom), visH = frEven(outH / zoom);
    const cropW = Math.min(visW, evenSrcW), cropH = Math.min(visH, evenSrcH);

    let offX = frRound((srcW - cropW) * conf.focus_x / 100);
    let offY = frRound((srcH - cropH) * conf.focus_y / 100);
    offX = clamp(offX, 0, Math.max(0, srcW - cropW));
    offY = clamp(offY, 0, Math.max(0, srcH - cropH));

    const cropped = cropW !== evenSrcW || cropH !== evenSrcH;
    return { width: outW, height: outH, changed: zoom !== 1 ? true : cropped,
             aspect: conf.aspect, fit: "crop",
             crop: { x: offX, y: offY, w: cropW, h: cropH },
             zoom, sharpness: Math.round((cropW / outW) * 1000) / 1000 };
  }

  // 여백 채우기 — 원본의 긴 변을 새 틀의 긴 변으로 삼는다 (framing.py 의 설명 참고)
  const longSide = Math.max(srcW, srcH);
  let outW, outH;
  if (targetRatio >= 1) { outW = frEven(longSide); outH = frEven(longSide / targetRatio); }
  else { outH = frEven(longSide); outW = frEven(longSide * targetRatio); }

  // 틀 안에 원본 전체가 들어가도록 줄인 크기 (확대 없을 때).
  let fitW, fitH;
  if (sourceRatio > outW / outH) { fitW = outW; fitH = frEven(outW / sourceRatio); }
  else { fitH = outH; fitW = frEven(outH * sourceRatio); }

  if (zoom === 1) {
    const changed = outW !== evenSrcW || outH !== evenSrcH;
    return { width: outW, height: outH, changed, aspect: conf.aspect, fit: "pad", crop: null,
             zoom: 1, sharpness: Math.round((srcW / fitW) * 1000) / 1000 };
  }
  const zoomW = frEven(fitW * zoom);
  return { width: outW, height: outH, changed: true, aspect: conf.aspect, fit: "pad", crop: null,
           zoom, sharpness: Math.round((srcW / zoomW) * 1000) / 1000 };
}

/** 프로젝트에 저장된 화면비 설정 (없으면 기본값). */
function currentOutput() {
  return normalizeOutput(project && project.output);
}

/** 지금 미리보기에 보이는 그림의 실제 픽셀 크기. 아직 못 읽었으면 null.
 *
 *  사진 프로젝트에서 이 함수가 null 을 돌려주면 outputFrameRect() 가 통째로
 *  무력해져서 **자막을 그리는 자리와 실제로 새겨지는 자리가 어긋난다**
 *  (memory/preview-must-use-the-output-frame.md 에서 438픽셀까지 벌어졌다).
 *  그래서 영상이 없으면 지금 보이는 사진의 크기를, 그것도 없으면 캔버스를 쓴다.
 */
function sourceDimensions() {
  const p = $("#player");
  if (p && p.videoWidth && p.videoHeight) return { w: p.videoWidth, h: p.videoHeight };

  const img = $("#player-img");
  if (img && !img.hidden && img.naturalWidth && img.naturalHeight) {
    return { w: img.naturalWidth, h: img.naturalHeight };
  }

  if (project && (hasImages() || project.audio_path)) {
    const canvas = projectCanvas();
    return { w: canvas.width, h: canvas.height };
  }
  return null;
}

/** 미리보기 위의 화면비 틀을 지금 설정대로 다시 그린다 (F-C ⓐ). */
function applyFrameGuide() {
  const guide = $("#frame-guide");
  const win = $("#fg-window");
  const box = $("#video-box");
  const bg = $("#player-bg");
  if (!guide || !win || !box) return;

  const conf = currentOutput();
  const dims = sourceDimensions();

  // 사진 프로젝트에서는 상자를 지금 보이는 사진의 모양으로 만든다 (CSS 설명 참고).
  // 여백 채우기일 때는 상자가 곧 출력 틀이므로 그쪽 규칙에 양보한다.
  const stageImg = $("#player-img");
  const photoMode = hasImages() && stageImg && !stageImg.hidden
    && stageImg.naturalWidth > 0 && conf.fit !== "pad";
  box.classList.toggle("is-photo", !!photoMode);
  if (photoMode) {
    box.style.setProperty("--img-ar", `${stageImg.naturalWidth} / ${stageImg.naturalHeight}`);
  } else {
    box.style.removeProperty("--img-ar");
  }

  // 원본 그대로이거나 영상 크기를 아직 모르면 아무것도 겹치지 않는다
  if (conf.aspect === "source" || !dims) {
    guide.hidden = true;
    box.classList.remove("is-padded", "is-pad-black");
    box.style.removeProperty("--out-ar");
    if (bg) { bg.hidden = true; bg.removeAttribute("src"); }
    updateAspectReadout(null);
    return;
  }

  const frame = resolveFraming(dims.w, dims.h, conf);

  if (frame.fit === "pad") {
    // 여백 채우기: 상자 자체를 목표 화면비로 만들고 영상을 그 안에 담는다.
    // 잘리는 것이 없으므로 어둡게 덮지 않고 테두리만 두른다.
    box.classList.add("is-padded");
    box.classList.toggle("is-pad-black", !conf.pad_blur);
    box.style.setProperty("--out-ar", `${frame.width} / ${frame.height}`);
    guide.hidden = false;
    win.style.left = "0"; win.style.top = "0";
    win.style.width = "100%"; win.style.height = "100%";
    win.style.boxShadow = "none";
    win.classList.add("is-fixed");
    syncBlurBackground(conf.pad_blur);
  } else {
    box.classList.remove("is-padded", "is-pad-black");
    box.style.removeProperty("--out-ar");
    syncBlurBackground(false);

    guide.hidden = false;
    win.style.boxShadow = "";  // CSS 기본값(바깥을 어둡게)으로 되돌린다
    win.style.left = `${frame.crop.x / dims.w * 100}%`;
    win.style.top = `${frame.crop.y / dims.h * 100}%`;
    win.style.width = `${frame.crop.w / dims.w * 100}%`;
    win.style.height = `${frame.crop.h / dims.h * 100}%`;
    // 남는 여유가 없으면(예: 정확히 들어맞는 화면비) 끌 것이 없다
    const slack = (dims.w - frame.crop.w) > 0 || (dims.h - frame.crop.h) > 0;
    win.classList.toggle("is-fixed", !slack);
  }

  updateAspectReadout({ frame, dims, conf });
}

/** 지금 보이는 자막이 출력 틀 밖으로 얼마나 나가는지 (픽셀). 안 나가면 null.
 *
 *  화면비를 좁히면 자막 글은 그대로인데 틀만 좁아져서, 가장자리에 둔 자막이 결과물에서
 *  잘려 나간다. 미리보기에서 눈에 보이더라도 **말로도 알려 줘야** 놓치지 않는다.
 */
function subtitleOverflow() {
  const overlay = $("#overlay");
  const box = $("#video-box");
  if (!overlay || !box || overlay.hidden || !(overlay.textContent || "").trim()) return null;

  const fr = outputFrameRect();
  const b = box.getBoundingClientRect();
  const o = overlay.getBoundingClientRect();
  if (!b.width || !b.height || !o.width) return null;

  const frameLeft = b.left + b.width * fr.left;
  const frameTop = b.top + b.height * fr.top;
  const over = {
    left: Math.max(0, frameLeft - o.left),
    right: Math.max(0, o.right - (frameLeft + b.width * fr.w)),
    top: Math.max(0, frameTop - o.top),
    bottom: Math.max(0, o.bottom - (frameTop + b.height * fr.h)),
  };
  // 화면에 그려진 크기를 원본 픽셀로 환산해 둔다 (사용자에게 보여 줄 때 뜻이 통하도록)
  const dims = sourceDimensions();
  const perPx = dims ? dims.w / b.width : 1;
  const worst = Math.max(over.left, over.right, over.top, over.bottom);
  return worst > 1 ? { ...over, worst, sourcePixels: Math.round(worst * perPx) } : null;
}

/** 자막이 잘릴 상황이면 경고를 띄우고, 아니면 감춘다. */
function refreshSubtitleFitWarning() {
  const el = $("#subtitle-fit-warn");
  if (!el) return;
  const over = currentOutput().aspect === "source" ? null : subtitleOverflow();
  if (!over) { el.hidden = true; return; }

  const sides = [];
  if (over.left > 1) sides.push("왼쪽");
  if (over.right > 1) sides.push("오른쪽");
  if (over.top > 1) sides.push("위");
  if (over.bottom > 1) sides.push("아래");
  el.textContent =
    `⚠ 자막이 ${sides.join("·")}으로 약 ${over.sourcePixels}픽셀 넘칩니다. ` +
    `지금 내보내면 그만큼 잘려 나갑니다. ` +
    `자막을 안쪽으로 옮기거나, [글꼴]의 크기를 줄이거나, [줄바꿈 규칙]의 ` +
    `'한 줄 최대 글자'를 줄여 주세요.`;
  el.hidden = false;
}

/** 여백 채우기의 흐린 배경 영상을 본 영상과 같은 지점으로 맞춘다. */
function syncBlurBackground(on) {
  const bg = $("#player-bg");
  const p = $("#player");
  if (!bg || !p) return;

  // 사진 프로젝트는 배경도 사진이다. 영상용 배경은 끄고 사진 배경을 쓴다.
  if (hasImages()) {
    const bgImg = $("#player-bg-img");
    const img = $("#player-img");
    bg.hidden = true;
    if (bg.src) { bg.removeAttribute("src"); bg.load(); }
    if (bgImg && img) {
      if (on && img.getAttribute("src")) {
        bgImg.src = img.getAttribute("src");
        bgImg.hidden = false;
      } else {
        bgImg.hidden = true;
        bgImg.removeAttribute("src");
      }
    }
    return;
  }
  const bgImg = $("#player-bg-img");
  if (bgImg) { bgImg.hidden = true; bgImg.removeAttribute("src"); }

  if (!on || !p.src) {
    bg.hidden = true;
    if (bg.src) { bg.removeAttribute("src"); bg.load(); }
    return;
  }
  if (bg.getAttribute("src") !== p.getAttribute("src")) {
    bg.src = p.getAttribute("src");
  }
  bg.hidden = false;
  // 0.3초 넘게 벌어졌을 때만 맞춘다. 매번 맞추면 재생이 튄다.
  if (Math.abs((bg.currentTime || 0) - p.currentTime) > 0.3) bg.currentTime = p.currentTime;
  if (p.paused) { bg.pause(); } else if (bg.paused) { bg.play().catch(() => {}); }
}

/** 화면비 설정 아래에 "무엇이 어떻게 되는지"를 글로 적어 준다. */
function updateAspectReadout(info) {
  const el = $("#aspect-readout");
  if (!el) return;
  if (!info) {
    const dims = sourceDimensions();
    el.textContent = dims
      ? `원본 ${dims.w}×${dims.h} 그대로 내보냅니다.`
      : "영상을 불러오면 결과 크기를 알려 드립니다.";
    return;
  }
  const { frame, dims, conf } = info;
  const size = `${dims.w}×${dims.h} → ${frame.width}×${frame.height}`;
  if (frame.fit === "pad") {
    const filler = conf.pad_blur ? "흐린 배경" : "검은색";
    el.textContent = `${size} · 원본 전체가 들어가고 남는 곳은 ${filler}으로 채웁니다. 잘리는 부분이 없습니다.`;
  } else {
    const cutW = dims.w - frame.crop.w, cutH = dims.h - frame.crop.h;
    const cut = cutW > 0
      ? `좌우에서 ${cutW}픽셀`
      : (cutH > 0 ? `위아래에서 ${cutH}픽셀` : "잘리는 부분 없이");
    el.textContent = `${size} · ${cut} 잘라 냅니다. 남길 자리는 아래 막대나 미리보기 틀로 옮길 수 있습니다.`;
  }
}

/** 화면비 설정을 바꾸고 저장한다. */
function setOutput(patch, { snap = true } = {}) {
  if (!project) return;
  if (snap) snapshot();
  project.output = normalizeOutput(Object.assign({}, currentOutput(), patch));
  // 사진 프로젝트는 **화면비를 고르는 것이 곧 출력 크기를 정하는 것**이다.
  // 원본이 여럿이라 기준이 없기 때문이다. 그래서 캔버스를 따라 바꿔 준다.
  if (hasImages()) project.canvas = projectCanvas();
  syncAspectInputs();
  applyFrameGuide();
  applyOverlayStyle();
  markDirty();
}

/** 화면비 관련 입력칸·단추를 지금 설정에 맞춘다. */
function syncAspectInputs() {
  const conf = currentOutput();
  $$(".aspect-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.aspect === conf.aspect));
  $$(".fit-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.fit === conf.fit));

  const opts = $("#aspect-options");
  if (opts) opts.hidden = conf.aspect === "source";

  const cropOpts = $("#crop-options"), padOpts = $("#pad-options");
  if (cropOpts) cropOpts.hidden = conf.fit !== "crop";
  if (padOpts) padOpts.hidden = conf.fit !== "pad";

  // 위치 막대는 **가로·세로 두 개**다. 확대를 하면 두 축 모두 움직일 자리가 생기므로
  // 막대 하나로 축을 골라 쓰던 옛 방식은 한쪽 축을 잠가 버린다 (오류 없이 안 움직인다).
  const dims = sourceDimensions();
  const zoomSlider = $("#aspect-zoom");
  const frame = dims ? resolveFraming(dims.w, dims.h, conf) : null;

  if (zoomSlider) zoomSlider.value = String(conf.zoom);
  const zoomLabel = $("#zoom-val");
  if (zoomLabel) zoomLabel.textContent = `${conf.zoom.toFixed(2).replace(/0$/, "")}배`;
  const zoomWarn = $("#zoom-warn");
  // 원본 화소가 출력의 3/4 아래로 떨어지면 눈에 띄게 흐려진다
  // (실측: 1280×720 을 9:16 으로 1.6배 당기면 선명도가 41% 떨어진다).
  if (zoomWarn) zoomWarn.hidden = !frame || (frame.sharpness ?? 1) >= 0.75;

  for (const axis of ["x", "y"]) {
    const slider = $(`#aspect-focus-${axis}`);
    if (!slider) continue;
    const value = axis === "x" ? conf.focus_x : conf.focus_y;
    slider.value = String(value);
    // 움직일 자리가 없으면 흐리게 해서 "왜 안 움직이는지"가 보이게 한다.
    const slack = !frame || !frame.crop ? 0
      : (axis === "x" ? dims.w - frame.crop.w : dims.h - frame.crop.h);
    slider.disabled = slack <= 0;
    const label = $(`#focus-${axis}-val`);
    if (!label) continue;
    if (slack <= 0) { label.textContent = "움직일 자리 없음"; continue; }
    label.textContent = axis === "x"
      ? (value <= 15 ? "왼쪽" : value >= 85 ? "오른쪽" : value === 50 ? "가운데" : `왼쪽에서 ${value}%`)
      : (value <= 15 ? "위쪽" : value >= 85 ? "아래쪽" : value === 50 ? "가운데" : `위에서 ${value}%`);
  }

  const blur = $("#aspect-pad-blur");
  if (blur) blur.checked = conf.pad_blur;
}

function wireAspectPanel() {
  $$(".aspect-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const aspect = btn.dataset.aspect;
      setOutput({ aspect });
      toast(`화면비를 ${FR_ASPECT_LABELS[aspect]}(으)로 바꿨습니다.`);
    });
  });

  $$(".fit-btn").forEach((btn) => {
    btn.addEventListener("click", () => setOutput({ fit: btn.dataset.fit }));
  });

  // 끄는 동안에는 되돌림점을 만들지 않는다. 한 번 끌 때마다 Ctrl+Z가 백 번 필요해진다.
  for (const axis of ["x", "y"]) {
    const slider = $(`#aspect-focus-${axis}`);
    if (!slider) continue;
    slider.addEventListener("input", () => {
      const v = clamp(parseFloat(slider.value) || 0, 0, 100);
      setOutput(axis === "x" ? { focus_x: v } : { focus_y: v }, { snap: false });
    });
    slider.addEventListener("change", () => snapshot());
  }

  const zoomSlider = $("#aspect-zoom");
  if (zoomSlider) {
    zoomSlider.addEventListener("input", () => {
      const v = clamp(parseFloat(zoomSlider.value) || 1, FR_ZOOM_MIN, FR_ZOOM_MAX);
      setOutput({ zoom: v }, { snap: false });
    });
    zoomSlider.addEventListener("change", () => snapshot());
  }

  const blur = $("#aspect-pad-blur");
  if (blur) blur.addEventListener("change", () => setOutput({ pad_blur: blur.checked }));

  wireFrameDrag();
}

/** 미리보기 틀을 마우스로 끌어 잘라낼 자리를 옮긴다 (F-C ⓑ 의 위치 지정). */
function wireFrameDrag() {
  const win = $("#fg-window");
  if (!win) return;
  let drag = null;

  win.addEventListener("pointerdown", (e) => {
    if (win.classList.contains("is-fixed")) return;
    const dims = sourceDimensions();
    if (!dims) return;
    const frame = resolveFraming(dims.w, dims.h, currentOutput());
    if (!frame.crop) return;

    const rect = $("#video-box").getBoundingClientRect();
    drag = {
      startX: e.clientX, startY: e.clientY,
      conf: currentOutput(),
      // 화면에 그려진 1픽셀이 원본 몇 픽셀인지
      scaleX: dims.w / rect.width, scaleY: dims.h / rect.height,
      slackX: dims.w - frame.crop.w, slackY: dims.h - frame.crop.h,
    };
    snapshot();
    win.setPointerCapture(e.pointerId);
    win.classList.add("is-dragging");
    e.preventDefault();
  });

  win.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const patch = {};
    if (drag.slackX > 0) {
      const moved = (e.clientX - drag.startX) * drag.scaleX;
      patch.focus_x = clamp(drag.conf.focus_x + (moved / drag.slackX) * 100, 0, 100);
    }
    if (drag.slackY > 0) {
      const moved = (e.clientY - drag.startY) * drag.scaleY;
      patch.focus_y = clamp(drag.conf.focus_y + (moved / drag.slackY) * 100, 0, 100);
    }
    setOutput(patch, { snap: false });
  });

  for (const ev of ["pointerup", "pointercancel"]) {
    win.addEventListener(ev, (e) => {
      if (!drag) return;
      drag = null;
      win.classList.remove("is-dragging");
      try { win.releasePointerCapture(e.pointerId); } catch { /* 이미 놓였으면 무시 */ }
    });
  }
}

// ══ 세로 영상(쇼츠) 자막 프리셋 ════════════════════════════
// 화면비 자체는 위의 [세로 9:16] 단추가 바꾼다. 이 단추는 **자막 모양**만 세로에 맞춘다.
function applyShortsPreset() {
  snapshot();
  // 쇼츠는 화면 위아래를 앱 UI가 가리므로 자막을 가운데 아래쪽 안전한 자리에 둔다
  project.style.position = { mode: "custom", preset: "bottom", x: 50, y: 74 };
  project.style.size = 52;
  project.style.max_chars = 13;   // 세로 화면은 한 줄이 짧아야 읽힌다
  project.style.max_lines = 2;
  project.style.outline.width = 3.5;
  syncStyleInputs(); applyOverlayStyle(); markDirty();
  $("#chk-safe-area").checked = true;
  $("#safe-area").hidden = false;
  toast("세로 영상용으로 자막 크기·줄바꿈·위치를 맞췄습니다. 안전 영역 안내선도 켰습니다.");
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

// ══ 색 고르기 ══════════════════════════════════════════════
// 브라우저 기본 색 고르기 창은 스포이드가 다른 창 뒤로 숨고 다른 프로그램 위까지
// 따라다녀 쓰기 어렵다. 자막에 쓰는 색은 몇 가지뿐이므로 칩과 색상 코드로 해결하고,
// 기본 창은 [다른 색…]에만 남겨 둔다.
// 대표 색만 칩으로 둔다. 그 밖의 색은 아래 색감표와 스포이드로 고른다.
const SWATCHES = [
  ["#FFFFFF", "흰색"], ["#000000", "검정"], ["#FFE14D", "노랑"], ["#FFB020", "주황"],
  ["#FF6B6B", "빨강"], ["#7CD9FF", "하늘"], ["#8CE99A", "연두"], ["#FF9ECF", "분홍"],
];

// ── 색 계산 ────────────────────────────────────────────────
function hsvToHex(h, s, v) {
  const f = (n) => {
    const k = (n + h / 60) % 6;
    const x = v - v * s * Math.max(0, Math.min(k, 4 - k, 1));
    return Math.round(x * 255).toString(16).padStart(2, "0");
  };
  return ("#" + f(5) + f(3) + f(1)).toUpperCase();
}

// 흰색·검정처럼 **색기가 없는 색**은 '색상(Hue)'이라는 값 자체가 없다.
// 보통은 0으로 두는데, 0은 빨강이라 색감표 전체가 새빨갛게 칠해진다.
// 자막 기본값이 흰 글자 + 검은 외곽선이라 처음 열 때마다 붉은 판이 두 개 뜨고,
// 그게 눈을 어지럽게 한다. 그래서 색기가 없을 때는 앱의 '하늘' 견본과 같은
// 색상값을 쓴다 (#7CD9FF = 197도, 색상 띠에서 약 55% 지점 ≒ 가운데).
//
// 고른 색 자체는 바뀌지 않는다. 흰색은 그대로 #FFFFFF 다. 바뀌는 것은
// **색감표의 바탕색과 띠 손잡이 위치**뿐이다. 색감표를 끌면 그 자리에서
// 하늘색 계열이 나오므로 동작도 보이는 것과 어긋나지 않는다.
const NEUTRAL_HUE = 197;

function hexToHsv(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(hex || "").trim());
  if (!m) return { h: NEUTRAL_HUE, s: 0, v: 1 };
  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = NEUTRAL_HUE;
  if (d) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  return { h, s: max ? d / max : 0, v: max };
}

function buildColorPicks() {
  document.querySelectorAll(".color-pick").forEach((box) => {
    if (box.dataset.built) return;
    const native = document.getElementById(box.dataset.target);
    if (!native) return;

    box.innerHTML =
      `<div class="cp-sv" tabindex="0" role="application" aria-label="색감표: 끌어서 색을 고릅니다">` +
      `<div class="cp-dot"></div></div>` +
      `<div class="cp-hue" tabindex="0" role="slider" aria-label="색상 띠">` +
      `<div class="cp-hue-dot"></div></div>` +
      `<div class="cp-row">` +
      `<span class="cp-preview" aria-hidden="true"></span>` +
      `<input type="text" class="cp-hex" maxlength="7" spellcheck="false" placeholder="#RRGGBB" aria-label="색상 코드">` +
      `<button type="button" class="btn btn-tiny cp-drop" title="화면 어디서든 색을 집어 옵니다">스포이드</button>` +
      `</div>` +
      `<div class="sw-row">` +
      SWATCHES.map(([hex, name]) =>
        `<button type="button" class="sw" data-c="${hex}" style="background:${hex}" title="${name}" aria-label="${name}"></button>`
      ).join("") +
      `</div>`;

    const sv = box.querySelector(".cp-sv");
    const hue = box.querySelector(".cp-hue");

    // 색감표를 끌면 선명도(가로)와 밝기(세로)가 함께 정해진다
    const pickSV = (e) => {
      const r = sv.getBoundingClientRect();
      const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
      const cur = hexToHsv(native.value);
      setPickedColor(native, hsvToHex(cur.h, x, 1 - y));
    };
    const pickHue = (e) => {
      const r = hue.getBoundingClientRect();
      const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
      const cur = hexToHsv(native.value);
      setPickedColor(native, hsvToHex(x * 360, cur.s || 1, cur.v || 1));
    };
    const dragWith = (el, handler) => {
      el.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        el.setPointerCapture(e.pointerId);
        handler(e);
        const move = (ev) => handler(ev);
        const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
        el.addEventListener("pointermove", move);
        el.addEventListener("pointerup", up);
      });
    };
    dragWith(sv, pickSV);
    dragWith(hue, pickHue);

    box.querySelectorAll(".sw").forEach((sw) =>
      sw.addEventListener("click", () => setPickedColor(native, sw.dataset.c))
    );

    const hexInput = box.querySelector(".cp-hex");
    hexInput.addEventListener("change", () => {
      let v = hexInput.value.trim();
      if (v && !v.startsWith("#")) v = "#" + v;
      if (/^#[0-9a-fA-F]{6}$/.test(v)) setPickedColor(native, v.toUpperCase());
      else {
        toast("색상 코드는 #RRGGBB 형식으로 넣어 주세요. 예: #FFE14D", { error: true });
        refreshColorPicks();
      }
    });

    // 스포이드 — 브라우저 색 창을 거치지 않고 우리 화면에서 바로 부른다.
    // 화면 어디서든(다른 프로그램 위에서도) 색을 집을 수 있는 것이 이 도구의 쓸모다.
    const drop = box.querySelector(".cp-drop");
    if (!("EyeDropper" in window)) {
      drop.disabled = true;
      drop.title = "이 브라우저는 스포이드를 지원하지 않습니다. 색감표나 색상 코드를 써 주세요.";
    } else {
      drop.addEventListener("click", async () => {
        try {
          const res = await new window.EyeDropper().open();
          if (res?.sRGBHex) setPickedColor(native, res.sRGBHex.toUpperCase());
        } catch (_) {
          /* 사용자가 Esc로 취소한 경우 — 아무것도 하지 않는다 */
        }
      });
    }

    native.addEventListener("input", refreshColorPicks);
    box.dataset.built = "1";
  });
  refreshColorPicks();
}

function setPickedColor(native, hex) {
  native.value = hex;
  // 스타일을 실제로 반영하는 쪽은 기존 change 처리기다. 그대로 흘려보낸다.
  native.dispatchEvent(new Event("change", { bubbles: true }));
  refreshColorPicks();
}

function refreshColorPicks() {
  document.querySelectorAll(".color-pick").forEach((box) => {
    const native = document.getElementById(box.dataset.target);
    if (!native) return;
    const cur = (native.value || "#FFFFFF").toUpperCase();
    const { h, s, v } = hexToHsv(cur);

    const hexInput = box.querySelector(".cp-hex");
    if (hexInput && document.activeElement !== hexInput) hexInput.value = cur;

    const prev = box.querySelector(".cp-preview");
    if (prev) prev.style.background = cur;

    // 색감표의 바탕색을 지금 고른 색상(Hue)에 맞춘다
    const sv = box.querySelector(".cp-sv");
    if (sv) {
      sv.style.setProperty("--hue", hsvToHex(h, 1, 1));
      const dot = sv.querySelector(".cp-dot");
      if (dot) {
        dot.style.left = s * 100 + "%";
        dot.style.top = (1 - v) * 100 + "%";
        dot.style.background = cur;
      }
    }
    const hueDot = box.querySelector(".cp-hue-dot");
    if (hueDot) {
      hueDot.style.left = (h / 360) * 100 + "%";
      hueDot.style.background = hsvToHex(h, 1, 1);
    }

    box.querySelectorAll(".sw").forEach((sw) =>
      sw.classList.toggle("is-active", sw.dataset.c.toUpperCase() === cur)
    );
  });
}

// ══ 눌렀다는 반응 ══════════════════════════════════════════
function wirePressFeedback() {
  // 켜짐/꺼짐이 있는 단추는 눌린 채로 남지만, 한 번 실행하고 끝나는 단추
  // (문장 나누기 미리보기 등)는 남길 상태가 없다. 그래서 실행 직후 잠깐만
  // 눌린 모습을 유지해 "눌렸다"는 것을 눈으로 확인할 수 있게 한다.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".btn");
    if (!btn || btn.disabled || btn.classList.contains("is-on")) return;
    btn.classList.add("just-ran");
    setTimeout(() => btn.classList.remove("just-ran"), 280);
  });
}

// ══ 시작 ═══════════════════════════════════════════════════
async function boot() {
  wireStartScreen();
  wireEditor();
  wirePWA();
  wirePressFeedback();
  buildColorPicks();
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
