# TECH SPEC — SubCap Studio 기술 사양

버전 1.0 · 기술 결정의 기준 문서. 여기 명시된 스택·구조를 임의로 바꾸지 말 것 (변경이 필요하면 사용자에게 이유와 함께 제안).

## 1. 전체 구조: "로컬 웹앱"

```
[사용자 브라우저]  ←HTTP(localhost)→  [FastAPI 서버(Python)]
   화면(HTML/JS)                        ├─ STT: faster-whisper (로컬 음성인식)
   영상 미리보기                         ├─ TTS: edge-tts (나레이션 생성)
   자막 오버레이                         ├─ 자막: pysubs2 (SRT/ASS 처리)
                                       ├─ 렌더: FFmpeg (번인/합성/추출)
                                       └─ 저장: 프로젝트 JSON 파일
```

**왜 이 구조인가 (Electron/설치형 대비):**
- 비개발자 사용자가 실행할 때 실패 지점이 가장 적다 (run.bat 더블클릭 → 브라우저).
- Node/패키징 도구체인이 전혀 필요 없다 — Python + FFmpeg 두 개면 끝.
- Claude Code가 디버깅하기 쉽다 (서버 로그가 곧 진단 정보).

## 2. 기술 스택과 선정 이유

| 영역 | 선택 | 이유 | 대안(불채택 이유) |
|---|---|---|---|
| 백엔드 | Python 3.11 + FastAPI + uvicorn | AI 라이브러리 생태계, 단순함 | Node(도구체인 복잡) |
| 음성인식 | **faster-whisper** | 무료·로컬·한국어 양호, CPU 동작, 단어 타임스탬프 | 클라우드 STT(비용·개인정보) |
| TTS | **edge-tts** | 무료, 한국어 신경망 음성 품질 우수(SunHi, InJoon 등) | 클라우드 TTS(비용), pyttsx3(품질 낮음) |
| 자막 처리 | pysubs2 | SRT/VTT/ASS 읽기·쓰기·스타일 | 직접 파싱(재발명) |
| 렌더링 | FFmpeg (subprocess) | 사실상 표준, ASS 번인·오디오 합성 모두 처리 | moviepy(느리고 불안정) |
| 프론트엔드 | 순수 HTML/CSS/JS (빌드 없음) | 도구체인 제거, 유지보수 단순 | React+Vite(Node 필요) |
| 저장 | 프로젝트 폴더 내 JSON | 단순, 백업 쉬움 | DB(과잉) |

## 3. 위험 요소와 대응 (필수 반영)

| 위험 | 내용 | 대응 |
|---|---|---|
| R1 edge-tts 중단 | Edge TTS는 Microsoft 비공식 경로. 언제든 막힐 수 있음 | `app/core/tts/` 를 **어댑터 인터페이스**로 설계: `TTSEngine.synthesize(text, voice, rate) -> (wav_bytes, duration)`. 기본 구현은 EdgeTTS, 실패 시 UI에 안내 메시지. 교체 시 어댑터 하나만 추가 |
| R2 Whisper 정확도 | CPU+small 모델은 고유명사·전문용어에 약함 | ① 모델 크기 선택(small/medium) ② 사용자 사전 후처리(F-12) ③ 인식 직후 편집 UI로 바로 연결 |
| R3 처리 시간 | CPU에서 STT·렌더링이 느림 | 모든 장시간 작업은 백그라운드 작업 + 진행률 폴링 API. UI는 절대 멈추지 않는다 |
| R4 한글 폰트 번인 | libass가 폰트를 못 찾으면 네모 글자 | OFL 라이선스 한글 폰트(Pretendard 또는 Noto Sans KR)를 `assets/fonts/`에 번들하고 FFmpeg에 `fontsdir` 지정 |
| R5 미리보기≠최종 결과 | 브라우저 오버레이와 ASS 번인의 렌더링 차이 | 스타일 속성별 CSS↔ASS 매핑 표를 `app/core/style_map.py` 한 곳에서 관리. 근사치임을 UI에 표시하지 않아도 되나 매핑은 항상 이 파일 기준 |
| R6 경로 문제 | Windows 한글/공백 경로 | 모든 subprocess 호출에 인자 리스트 방식 사용(셸 문자열 조립 금지), pathlib 사용 |

## 4. 디렉터리 구조 (목표)

```
subcap-studio/
├─ run.bat                  # 사용자용 실행 (서버 기동 + 브라우저 열기)
├─ requirements.txt
├─ CLAUDE.md / README.md / PROMPTS.md / docs/ / memory/
├─ tools/
│   └─ check_env.py         # Python/FFmpeg/패키지 점검 + 설치 안내 출력
├─ app/
│   ├─ __main__.py          # uvicorn 기동
│   ├─ server.py            # FastAPI 앱, 라우트 등록
│   ├─ api/                 # 라우트: projects, stt, tts, subtitles, render, jobs
│   ├─ core/
│   │   ├─ stt.py           # faster-whisper 래퍼 (모델 로드 캐시)
│   │   ├─ tts/             # base.py(인터페이스), edge.py(기본 구현)
│   │   ├─ subtitles.py     # 세그먼트 모델, 분할/병합, SRT/VTT 입출력(pysubs2)
│   │   ├─ style_map.py     # 스타일 정의 + CSS↔ASS 매핑 (단일 출처)
│   │   ├─ ffmpeg.py        # 오디오 추출/번인/합성/덕킹 명령 조립
│   │   ├─ dictionary.py    # 사용자 사전
│   │   └─ jobs.py          # 백그라운드 작업 큐 + 진행률
│   └─ static/              # index.html, app.js, style.css (빌드 없음)
├─ assets/fonts/            # 번들 한글 폰트 (OFL)
├─ projects/                # 프로젝트별 폴더 (JSON + 생성 오디오 + 출력물)
└─ tests/sample/            # 테스트용 짧은 샘플 영상/대본 (Phase 0에서 생성)
```

## 5. 데이터 모델 (프로젝트 JSON)

```json
{
  "version": 1,
  "name": "0812_홍보영상",
  "video_path": "C:/.../원본.mp4",
  "mode": "video|script",
  "segments": [
    {"id": "s001", "start": 1.20, "end": 3.85, "text": "안녕하세요, 피엘에스입니다.",
     "tts": {"voice": "ko-KR-SunHiNeural", "rate": "+0%", "audio": "narr/s001.mp3", "duration": 2.41}}
  ],
  "style": {"preset": "basic", "font": "Pretendard", "size": 42, "color": "#FFFFFF",
             "outline": {"color": "#000000", "width": 2}, "shadow": true,
             "bg": {"enabled": false, "color": "#000000", "opacity": 0.5},
             "position": "bottom", "align": "center"},
  "narration": {"gap": 0.3, "global_rate": "+0%", "original_audio_volume": 30},
  "dictionary_applied": true
}
```

- `segments`가 유일한 진실 원천이다. SRT/ASS/타임라인/오버레이는 전부 여기서 파생된다.
- 대본 모드에서 타이밍 산출: `start[i] = start[i-1] + duration[i-1] + gap`, `end[i] = start[i] + duration[i]`.
- 문장 재생성 시(F-43): 해당 세그먼트 duration 갱신 후 이후 세그먼트 타이밍을 위 식으로 전부 재계산.

## 6. 핵심 API (요지)

```
POST /api/projects                      새 프로젝트 (파일 경로 등록)
GET/PUT /api/projects/{id}              프로젝트 읽기/저장(자동저장 포함)
POST /api/projects/{id}/stt             자막 자동 생성 시작 → job_id
POST /api/projects/{id}/tts             나레이션 생성 시작(전체/특정 세그먼트) → job_id
GET  /api/jobs/{job_id}                 진행률/상태/오류
POST /api/projects/{id}/render          내보내기(burn|mix|audio|srt|vtt) → job_id
GET  /api/tts/voices, POST /api/tts/preview   음성 목록/미리듣기
GET/PUT /api/dictionary                 사용자 사전
GET  /media/...                         영상/오디오 스트리밍 (Range 지원 필수 — 탐색 위해)
```

장시간 작업(stt/tts/render)은 전부 job 방식: 즉시 job_id 반환, 프론트가 1초 간격 폴링.

## 7. FFmpeg 명령 기준 (ffmpeg.py에서 조립)

```bash
# 1) 오디오 추출 (STT 입력용: 16kHz mono wav)
ffmpeg -y -i in.mp4 -vn -ac 1 -ar 16000 out.wav

# 2) 자막 번인 (ASS + 번들 폰트)
ffmpeg -y -i in.mp4 -vf "ass=subs.ass:fontsdir=assets/fonts" -c:a copy out.mp4

# 3) 나레이션 합성 (원본 소리 볼륨 조절 + 나레이션 믹스)
ffmpeg -y -i in.mp4 -i narration.mp3 -filter_complex \
  "[0:a]volume=0.3[bg];[bg][1:a]amix=inputs=2:duration=first:dropout_transition=0[a]" \
  -map 0:v -map "[a]" -c:v copy out.mp4
# (P2 덕킹: sidechaincompress 필터로 나레이션 구간만 원본 소리 자동 감쇠)

# 4) 번인+나레이션 동시: 2)와 3) 필터 결합 (비디오는 재인코딩 필요: -c:v libx264 -crf 18)
```

주의: 자막 필터 사용 시 비디오 재인코딩이 필수다(`-c:v copy` 불가). 오디오만 바꿀 때는 `-c:v copy`로 빠르게.

## 8. STT/TTS 세부

- faster-whisper: 최초 실행 시 모델 자동 다운로드(진행 안내 필수). `word_timestamps=True`로 받고, 세그먼트 분할은 문장부호 우선 + 한 줄 최대 20자·2줄 규칙(subtitles.py에서 규칙 함수로 분리).
- edge-tts 기본 음성 목록(최소): `ko-KR-SunHiNeural`(여), `ko-KR-InJoonNeural`(남), `en-US-JennyNeural`, `en-US-GuyNeural`. rate는 "-50%"~"+50%".
- 문장별 mp3를 projects/{id}/narr/ 에 저장하고 duration은 ffprobe로 실측한다 (추정 금지 — D1의 정확도가 여기서 나온다).

## 9. 프론트엔드 원칙

- `<video>` 태그 + `timeupdate` 이벤트로 현재 시간 추적 → 해당 세그먼트를 오버레이 div에 style_map 기반 CSS로 표시.
- 상태는 단일 JS 객체(project)로 관리하고, 변경 시 디바운스 2초 후 PUT 자동저장.
- 실행 취소(F-23)는 project 스냅샷 스택 방식(최대 50개)이면 충분하다. 복잡한 커맨드 패턴 불필요.
- 외부 CDN 의존 최소화(오프라인 실행 고려). 필요한 라이브러리는 static/vendor/에 내려받아 포함.
