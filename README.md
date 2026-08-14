<div align="center">

<img src="app/static/icons/icon-192.png" width="88" alt="">

# MovieFit Studio

**영상 자막을 자동으로 만들고, 대본으로 AI 나레이션까지 —
내 컴퓨터 안에서만 처리되는 무료 도구**

무료 · 워터마크 없음 · 계정 불필요 · 영상이 외부로 전송되지 않음

</div>

---

## 무엇을 하는 프로그램인가요

영상 편집기는 기능이 많은 대신 자막 하나 고치는 데도 여러 단계를 거쳐야 합니다.
MovieFit Studio는 **자막과 나레이션 두 가지만** 아주 잘하도록 만든 도구입니다.

**1. 영상 → 자막**
영상 파일을 넣으면 말을 알아듣고 자막을 만듭니다. 음성인식은 내 컴퓨터에서 돌아가므로
영상이 인터넷으로 나가지 않습니다. 만들어진 자막은 문서처럼 목록으로 보면서 고칩니다.

**2. 대본 → 나레이션 + 자막**
대본을 붙여넣으면 문장별로 나레이션 음성을 만들고, **각 문장 음성의 실제 길이를 재서
자막 타이밍을 자동으로 계산**합니다. 그래서 소리와 자막이 처음부터 정확히 맞습니다.
문장 하나를 고치면 그 문장만 다시 만들어지고 뒤쪽 타이밍이 알아서 밀립니다.

## 지금 상태

개발 중입니다. 아래 표가 현재 시점의 정직한 상태입니다.

| 단계 | 내용 | 상태 |
|---|---|---|
| Phase 0 | 서버 뼈대, 프로젝트 저장, 실행 스크립트, PWA | ✅ 완료 (검증됨) |
| — | 자막 스타일 전체, 자유 위치 배치, 타임라인, 목소리 선택·미리듣기 | ✅ 화면·설정 동작 |
| Phase 1 | 영상 → 자막 자동 생성, SRT 내보내기, 자막 번인 mp4 | 🚧 개발 중 |
| Phase 2 | 대본 → 나레이션 + 자막 타이밍 자동 산출 | 🚧 개발 중 |
| Phase 3 | 사용자 사전, 찾기/바꾸기, 문장 단위 재생성 | 📋 예정 |
| Phase 4 | 내 목소리 나레이션, 마이크 녹음, 자동 덕킹, 성능 마감 | 📋 예정 |

자세한 계획과 각 단계의 합격 기준은 [docs/ROADMAP.md](docs/ROADMAP.md)에 있습니다.

## 설치 방법

윈도우 10 / 11에서 동작합니다.

### 1단계 — 파이썬 설치

<https://www.python.org/downloads/> 에서 내려받아 설치합니다.
설치 화면 맨 아래 **"Add python.exe to PATH"** 를 반드시 체크하세요. 이걸 빼먹으면 실행이 안 됩니다.

### 2단계 — FFmpeg 설치

시작 메뉴에서 **PowerShell**을 열고 아래 한 줄을 붙여넣습니다.

```
winget install Gyan.FFmpeg
```

설치가 끝나면 열려 있던 검은 창을 모두 닫아야 인식됩니다.

### 3단계 — 프로그램 내려받기

이 페이지 위쪽의 초록색 **Code** 버튼 → **Download ZIP** 을 눌러 받은 뒤 압축을 풉니다.

### 4단계 — 실행

압축을 푼 폴더에서 **`run.bat`을 더블클릭**합니다.
처음 한 번은 필요한 부품을 자동으로 설치하느라 몇 분 걸립니다. 끝나면 브라우저가 저절로 열립니다.

> 문제가 생기면 폴더에서 `python tools/check_env.py` 를 실행해 보세요.
> 무엇이 빠졌는지, 어떻게 설치하는지 한국어로 알려줍니다.

## 자주 묻는 질문

**정말 무료인가요?**
네. 결제도 계정도 없고 워터마크도 붙지 않습니다.

**내 영상이 어디론가 전송되나요?**
아니요. 음성인식과 영상 처리는 전부 내 컴퓨터에서 이뤄집니다.
다만 **나레이션(AI 목소리) 생성은 인터넷이 필요합니다** — 읽을 문장 텍스트가 음성 서버로 전송됩니다.
영상이나 오디오 파일 자체는 어떤 경우에도 나가지 않습니다.

**GPU가 없어도 되나요?**
됩니다. 다만 자막 자동 생성이 더 오래 걸립니다. 진행률이 항상 표시됩니다.

**맥이나 리눅스에서도 되나요?**
현재는 윈도우 전용입니다. 파일 선택 창과 실행 스크립트가 윈도우 기준으로 만들어져 있습니다.

## 개발자를 위한 정보

```
python tools/check_env.py     환경 점검
python -m app                 개발용 서버 실행
python tests/smoke_test.py    동작 점검 (서버를 켠 상태에서)
python tools/make_icons.py    PWA 아이콘 다시 만들기
```

### 점검 목록

모두 **서버를 켠 상태에서** 하나씩 실행한다 (한꺼번에 돌리는 스크립트는 없다).

| 점검 | 무엇을 보나 | 필요한 것 |
|---|---|---|
| `tests/smoke_test.py` | 서버 기본 기능 전반 | — |
| `tests/guide_test.py` | 설명서 세 곳이 어긋나지 않는가 | — |
| `tests/errors_test.py` | 잘못된 입력에 한국어로 답하는가 | — |
| `tests/phase1_test.py` | 영상 → 자막 | 샘플 영상 |
| `tests/phase2_test.py` | 나레이션 | 인터넷 |
| `tests/phase3_test.py` | 편집 완성도 | 샘플 영상 |
| `tests/phase4_test.py` | 화면비 | 샘플 영상 |
| `tests/phase6_test.py` | 사진 영상·음원 영상·강제정렬 | 샘플 사진·음원 |
| `tests/filmstrip_test.py` | 타임라인의 영상 띠가 실제 장면과 맞는가 | — |
| `tests/bgm_test.py` | 배경음악이 실제로 깔리는가 | 샘플 영상 |
| `tests/ducking_test.py` | 나레이션 구간에서 원본 소리가 줄어드는가 (세기 3단계) | 인터넷 |
| `tests/ui_test.py` | 브라우저로 실제로 눌러 확인 | Playwright |
| `tests/phase6_ui_test.py` | 사진·음원 화면을 눌러 확인 | Playwright |
| `tests/shortcuts_test.py` | 단축키를 실제로 눌러 확인 | Playwright |
| `tests/longvideo_test.py` | 30분 영상 성능과 진행률 | **오래 걸림(10~40분)** |

시험용 파일은 저장소에 넣지 않는다. 없으면 만든다:

```
python tools/make_sample.py              색막대 영상 + 나레이션 견본
python tools/make_sample_images.py       크기·색이 제각각인 사진 (--count 30)
python tools/make_sample_speech.py       말소리가 든 영상 (인터넷 필요)
python tools/make_sample_long.py         30분짜리 긴 영상
```

브라우저 점검을 처음 돌린다면 Playwright(브라우저를 자동으로 조작하는 도구)를 설치한다:

```
python -m pip install playwright
python -m playwright install chromium
```

- 백엔드: Python 3.11 + FastAPI · 프론트엔드: 빌드 도구 없는 순수 HTML/CSS/JS
- 음성인식: faster-whisper (로컬) · 나레이션: edge-tts (교체 가능한 어댑터 구조)
- 구조와 기술 결정은 [docs/TECH_SPEC.md](docs/TECH_SPEC.md) 참고

## 라이선스

MIT License — [LICENSE](LICENSE) 참고. 외부 자산·상표 고지는 [NOTICE.md](NOTICE.md)에 정리했습니다.

함께 들어 있는 **Pretendard** 글꼴은 SIL Open Font License 1.1로 배포됩니다
([원본](https://github.com/orioncactus/pretendard)).

---

<sub>CapCut은 ByteDance Ltd.의 상표이며 본 프로젝트와 아무런 관련이 없습니다.
본 프로젝트는 어떤 회사의 후원이나 승인도 받지 않았습니다.</sub>
