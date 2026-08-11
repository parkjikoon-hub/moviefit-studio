/* CapCut Studio 프론트엔드
 *
 * 상태 관리 원칙 (TECH_SPEC 9절): 화면의 모든 내용은 아래 `project` 객체 하나에서 나온다.
 * 이 객체가 바뀌면 2초 뒤 서버에 자동 저장한다.
 */

"use strict";

// ── 전역 상태 ─────────────────────────────────────────────
let project = null;      // 현재 열려 있는 프로젝트 (서버의 project.json과 같은 모양)
let saveTimer = null;    // 자동 저장 디바운스 타이머

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ── 서버 통신 ─────────────────────────────────────────────
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let message = `서버 오류 (${res.status})`;
    try {
      const body = await res.json();
      if (body.detail) message = body.detail;
    } catch (_) { /* 본문이 JSON이 아니면 기본 메시지를 쓴다 */ }
    throw new Error(message);
  }
  return res.status === 204 ? null : res.json();
}

// ── 알림 ─────────────────────────────────────────────────
let toastTimer = null;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("is-error", isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 3000);
}

// ── 시간 표시 (초 → mm:ss.d) ──────────────────────────────
function fmtTime(seconds) {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const d = Math.floor((seconds * 10) % 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${d}`;
}

// ── 자동 저장 (F-02) ──────────────────────────────────────
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
      method: "PUT",
      body: JSON.stringify(project),
    });
    project.updated_at = saved.updated_at;
    state.textContent = "저장됨";
  } catch (err) {
    state.textContent = "저장 실패";
    toast(`저장하지 못했습니다: ${err.message}`, true);
  } finally {
    state.classList.remove("is-saving");
  }
}

// ── 화면 전환 ─────────────────────────────────────────────
function showStart() {
  project = null;
  $("#view-editor").hidden = true;
  $("#view-start").hidden = false;
  $("#player").removeAttribute("src");
  $("#player").load();
  loadRecent();
  history.replaceState(null, "", "/");
}

function showEditor() {
  $("#view-start").hidden = true;
  $("#view-editor").hidden = false;
}

// ── 최근 프로젝트 목록 ────────────────────────────────────
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
      const modeLabel = p.mode === "script" ? "대본" : "영상";
      meta.textContent = `${modeLabel} · 자막 ${p.segment_count}개 · ${p.updated_at}`;

      const del = document.createElement("button");
      del.className = "r-del";
      del.title = "이 프로젝트 삭제";
      del.textContent = "✕";
      del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`'${p.name}' 프로젝트를 삭제할까요?\n되돌릴 수 없습니다.`)) return;
        try {
          await api(`/api/projects/${encodeURIComponent(p.id)}`, { method: "DELETE" });
          toast("프로젝트를 삭제했습니다.");
          loadRecent();
        } catch (err) { toast(err.message, true); }
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

// ── 프로젝트 열기 / 만들기 ────────────────────────────────
async function openProject(id) {
  try {
    project = await api(`/api/projects/${encodeURIComponent(id)}`);
  } catch (err) {
    toast(err.message, true);
    return;
  }
  renderProject();
  showEditor();
  history.replaceState(null, "", `/?project=${encodeURIComponent(id)}`);
}

async function createProject({ name, video_path, mode }) {
  try {
    const created = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, video_path, mode }),
    });
    project = created;
    renderProject();
    showEditor();
    history.replaceState(null, "", `/?project=${encodeURIComponent(created.id)}`);
    toast("새 프로젝트를 만들었습니다.");
  } catch (err) {
    toast(err.message, true);
  }
}

// ── 프로젝트 내용을 화면에 그리기 ─────────────────────────
function renderProject() {
  if (!project) return;

  $("#project-name").value = project.name;
  $("#save-state").textContent = "저장됨";

  setMode(project.mode, false);

  const player = $("#player");
  if (project.video_path) {
    player.src = `/media/project/${encodeURIComponent(project.id)}/video`;
    player.hidden = false;
    $("#no-video").hidden = true;
    $("#file-info").textContent = project.video_path;
  } else {
    player.removeAttribute("src");
    player.hidden = true;
    $("#no-video").hidden = false;
    $("#file-info").textContent = "파일 없음 (대본 모드)";
  }

  $("#script-input").value = project.script || "";
  $("#stt-language").value = project.stt?.language ?? "ko";
  $("#stt-model").value = project.stt?.model ?? "small";
  $("#tts-voice").value = project.narration?.voice ?? "ko-KR-SunHiNeural";
  $("#tts-gap").value = project.narration?.gap ?? 0.3;
  $("#tts-volume").value = project.narration?.original_audio_volume ?? 30;
  $("#style-size").value = project.style?.size ?? 42;
  $("#style-color").value = project.style?.color ?? "#FFFFFF";
  $("#style-position").value = project.style?.position ?? "bottom";

  renderSegments();
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

// ── 세그먼트 목록 (Phase 1에서 편집 기능이 붙는다) ────────
function renderSegments() {
  const list = $("#seg-list");
  const segments = project?.segments ?? [];
  $("#seg-count").textContent = `${segments.length}개`;

  if (!segments.length) {
    list.innerHTML =
      '<li class="empty">아직 자막이 없습니다. 왼쪽에서 [자막 자동 생성]을 누르거나 대본 모드로 시작하세요.</li>';
    return;
  }
  list.innerHTML = "";
  for (const seg of segments) {
    const li = document.createElement("li");
    li.className = "seg-item";
    li.textContent = `${fmtTime(seg.start)} → ${fmtTime(seg.end)}  ${seg.text}`;
    list.appendChild(li);
  }
}

// ── 플레이어 자막 오버레이 (F-24) ─────────────────────────
function updateOverlay(currentTime) {
  const overlay = $("#overlay");
  const seg = (project?.segments ?? []).find((s) => currentTime >= s.start && currentTime <= s.end);
  overlay.textContent = seg ? seg.text : "";
}

// ── 이벤트 연결 ───────────────────────────────────────────
function wireStartScreen() {
  const pick = async () => {
    try {
      const result = await api("/api/system/pick-file", { method: "POST" });
      if (result.cancelled) return;
      const baseName = result.name.replace(/\.[^.]+$/, "");
      await createProject({ name: baseName, video_path: result.path, mode: "video" });
    } catch (err) {
      toast(err.message, true);
    }
  };

  const zone = $("#drop-zone");
  zone.addEventListener("click", pick);
  zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });

  // 브라우저는 보안상 끌어다 놓은 파일의 전체 경로를 알려주지 않으므로 안내만 한다
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("is-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("is-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("is-over");
    toast("브라우저 보안상 끌어다 놓기로는 파일 위치를 알 수 없습니다. 상자를 눌러 파일을 선택해 주세요.");
  });

  $("#btn-manual-open").addEventListener("click", async () => {
    const path = $("#manual-path").value.trim().replace(/^"|"$/g, "");
    if (!path) { toast("파일 경로를 입력해 주세요.", true); return; }
    const baseName = path.split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
    await createProject({ name: baseName, video_path: path, mode: "video" });
  });

  $("#btn-start-script").addEventListener("click", () => {
    const stamp = new Date().toLocaleDateString("ko-KR").replace(/[.\s]/g, "").slice(0, 8);
    createProject({ name: `${stamp}_나레이션`, video_path: null, mode: "script" });
  });
}

function wireEditor() {
  $("#btn-home").addEventListener("click", async () => {
    clearTimeout(saveTimer);
    await saveNow();
    showStart();
  });

  $("#project-name").addEventListener("input", (e) => {
    project.name = e.target.value;
    markDirty();
  });

  $("#mode-video").addEventListener("click", () => setMode("video"));
  $("#mode-script").addEventListener("click", () => setMode("script"));

  $("#script-input").addEventListener("input", (e) => { project.script = e.target.value; markDirty(); });

  // 우 패널 탭
  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".tab-btn").forEach((b) => b.classList.toggle("is-active", b === btn));
      $$(".tab-page").forEach((p) => { p.hidden = p.dataset.page !== btn.dataset.tab; });
    });
  });

  // 설정값 변경 → 프로젝트에 반영 + 자동 저장
  const bind = (sel, apply) => $(sel).addEventListener("change", (e) => { apply(e.target.value); markDirty(); });
  bind("#stt-language", (v) => { project.stt.language = v; });
  bind("#stt-model", (v) => { project.stt.model = v; });
  bind("#tts-voice", (v) => { project.narration.voice = v; });
  bind("#tts-gap", (v) => { project.narration.gap = parseFloat(v); });
  bind("#tts-volume", (v) => { project.narration.original_audio_volume = parseInt(v, 10); });
  bind("#style-color", (v) => { project.style.color = v; applyOverlayStyle(); });
  bind("#style-position", (v) => { project.style.position = v; applyOverlayStyle(); });
  $("#style-size").addEventListener("input", (e) => {
    project.style.size = parseInt(e.target.value, 10);
    applyOverlayStyle();
    markDirty();
  });

  $$(".preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".preset").forEach((b) => b.classList.toggle("is-active", b === btn));
      project.style.preset = btn.dataset.preset;
      markDirty();
    });
  });

  // 아직 연결되지 않은 기능은 솔직하게 알린다
  $("#btn-stt").addEventListener("click", () => toast("자막 자동 생성은 Phase 1에서 연결됩니다."));
  $("#btn-tts").addEventListener("click", () => toast("나레이션 생성은 Phase 2에서 연결됩니다."));
  $("#btn-export").addEventListener("click", () => toast("내보내기는 Phase 1에서 연결됩니다."));
  $("#btn-seg-add").addEventListener("click", () => toast("세그먼트 추가는 Phase 1에서 연결됩니다."));

  // 플레이어
  const player = $("#player");
  player.addEventListener("timeupdate", () => {
    $("#time-now").textContent = fmtTime(player.currentTime);
    updateOverlay(player.currentTime);
  });
  player.addEventListener("loadedmetadata", () => {
    $("#time-total").textContent = fmtTime(player.duration);
  });
  player.addEventListener("error", () => {
    if (player.getAttribute("src")) toast("영상을 재생할 수 없습니다. 파일이 이동되었거나 지원하지 않는 코덱일 수 있습니다.", true);
  });
  $("#btn-play").addEventListener("click", () => (player.paused ? player.play() : player.pause()));
  player.addEventListener("play", () => ($("#btn-play").textContent = "⏸"));
  player.addEventListener("pause", () => ($("#btn-play").textContent = "▶"));

  // 단축키 (UI_SPEC 3절 — Phase 0에서는 재생/이동만)
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (typing || $("#view-editor").hidden) return;
    if (e.key === " ") { e.preventDefault(); player.paused ? player.play() : player.pause(); }
    else if (e.key === "ArrowLeft")  { e.preventDefault(); player.currentTime -= e.shiftKey ? 0.1 : 1; }
    else if (e.key === "ArrowRight") { e.preventDefault(); player.currentTime += e.shiftKey ? 0.1 : 1; }
  });

  // 창을 닫기 전에 저장되지 않은 내용을 넘기지 않는다
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

function applyOverlayStyle() {
  const overlay = $("#overlay");
  const st = project?.style;
  if (!st) return;
  overlay.style.color = st.color;
  overlay.style.fontSize = `${Math.round(st.size * 0.62)}px`; // 미리보기 크기 근사
  overlay.style.bottom = st.position === "bottom" ? "8%" : st.position === "middle" ? "45%" : "auto";
  overlay.style.top = st.position === "top" ? "8%" : "auto";
}

// ── PWA (앱으로 설치) ─────────────────────────────────────
function wirePWA() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => { /* 설치 실패해도 앱은 정상 동작한다 */ });
  }

  let installPrompt = null;
  const btn = $("#btn-install");
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installPrompt = e;
    btn.hidden = false;
  });
  btn.addEventListener("click", async () => {
    if (!installPrompt) return;
    installPrompt.prompt();
    await installPrompt.userChoice;
    installPrompt = null;
    btn.hidden = true;
  });
}

// ── 시작 ─────────────────────────────────────────────────
async function boot() {
  wireStartScreen();
  wireEditor();
  wirePWA();

  try {
    const info = await api("/api/system/info");
    $("#env-info").textContent = `버전 ${info.version} · 파이썬 ${info.python}`;
  } catch (_) { /* 정보 표시는 없어도 그만 */ }

  // 주소에 프로젝트가 지정되어 있으면 바로 연다 (새로고침해도 작업이 유지된다)
  const requested = new URLSearchParams(location.search).get("project");
  if (requested) await openProject(requested);
  else await loadRecent();
}

boot();
