# 배포 순서표

> **v1.0** | 최종 업데이트: **2026-11-04 14:40** | 작성자: Claude Code

## 변경 이력

| 버전 | 일시 | 주요 변경 |
|------|------|---------|
| v1.0 | 2026-11-04 14:40 | 초기 작성. 인수인계 문서마다 흩어져 있던 순서(`handover_20260815_1655.md` 6절)를 옮기고, v0.7.0 배포에서 더한 것(나레이션 부품 최신 판, 거절 번호 보기, 설치 크기 본문 숫자)을 넣었다 |

새 판을 공개할 때 이 순서를 따른다. **공개(7·8단계)는 사용자 허락을 받고 한다.**
한 단계라도 건너뛰면 그 사실을 사용자에게 말한다.

## 0. 내보내기 전에 볼 것 (점검이 못 잡는 것들)

| # | 할 일 | 왜 |
|---|---|---|
| 0 | `git log <지난태그>..HEAD` 를 훑고, 새 기능마다 `docs/USER_GUIDE.md` 에 장이 있는지 찾는다 | 설명서에 없으면 내려받은 사람은 기능이 있는 줄 모른다 (`memory/release-needs-the-manual-too.md`) |
| 0-1 | 설명서와 소개 사이트의 "안 되는 것" 목록에 이제 되는 것이 남아 있지 않은가 | 옛 문구가 조용히 거짓말이 된다 |
| 0-2 | `landing/index.html` 에 박힌 숫자: 날짜, 점검 묶음 수, **설치 파일 크기**(내려받기 단추 셋 + 본문 "크기는 약 ○MB") | 단추만 고치고 본문을 빠뜨린 적이 있다 |
| 0-3 | `python -m pip index versions edge-tts` 의 최신 판이 `requirements.txt` 하한과 같은가 | 낡은 판은 마이크로소프트가 403 으로 막아 나레이션이 통째로 죽는다 (`memory/edge-tts-must-stay-current.md`) |

## 1~5. 만들기

1. `app/__init__.py` 의 `__version__` 을 올린다. 설명서 두 벌과 설치 파일 판 번호가 여기를 따라간다
2. `docs/USER_GUIDE.md` 머리말의 "대상 프로그램 버전"과 변경 이력을 고치고 `python tools/build_guide.py`
3. `docs/release_notes_vX.Y.Z.md` 를 쓴다 (앞 판 것을 본으로)
4. 개발 서버를 **새로 켜고**(`python -m app --port 8766`) 22개 묶음을 돌린다.
   `MOVIEFIT_TEST_URL=http://127.0.0.1:8766`, `MOVIEFIT_TEST_PROJECTS` 는 지운다, `PYTHONIOENCODING=utf-8`.
   나레이션 묶음이 `WSServerHandshakeError` 로 죽으면 **서버 기록에서 번호를 본다** — 403 은 부품이 낡은 것, 503 은 서버가 잠시 바쁜 것이다
5. `python tools/build_installer.py` → `build/dist/MovieFitStudio-Setup.exe`

## 6. 이 컴퓨터에 설치해 확인

1. **8765 와 8766 을 모두 끈다.** 개발 서버만 떠 있어도 설치가 막힌다 (`memory/installed-app-needs-restart.md`)
2. 작업 폴더 개수를 세어 둔다 (`%LOCALAPPDATA%\Programs\MovieFit Studio\projects`)
3. 설치 파일로 설치한다. 조용한 설치가 종료코드 1 로 끝나면 `/LOG=<경로>` 를 붙여 다시 돌려 이유를 본다
4. 확인할 것
   - 설치본이 보고하는 판 번호 (`/api/health`)
   - **설치본 파이썬으로** `import edge_tts; print(edge_tts.__version__)` 이 새 판인가 (개발 환경에서 되는 것은 증거가 아니다)
   - 작업 폴더 개수가 그대로인가
   - 평소 쓰던 크롬으로 **강력 새로고침 없이** 열어 새 화면이 나오는가 (브라우저가 옛 화면 파일을 붙잡고 있을 수 있다)
   - 옛 판과 값이 다른 자리 하나를 실제로 불러 본다

## 7~9. 공개

7. `git push` → `git tag vX.Y.Z` → `git push origin vX.Y.Z` →
   `gh release create vX.Y.Z build/dist/MovieFitStudio-Setup.exe --title ... --notes-file docs/release_notes_vX.Y.Z.md`.
   `releases/latest` 가 새 판을 가리키는지, 내려받기 주소가 200 을 주는지 본다
8. `Push-Location landing; vercel deploy --prod; Pop-Location` — `--cwd` 는 CLI 58 에서 "Not authorized" 로 죽는다.
   출력에 `Aliased https://moviefit-studio.vercel.app` 줄이 있어야 운영에 올라간 것이다 (`memory/vercel-landing-is-cli-deployed.md`)
9. 사이트가 주는 `index.html`·`guide.html` 과 로컬 파일을 비교한다. 양쪽을 `.replace('\r\n','\n')` 로 맞춘 뒤 비교한다 (줄바꿈 때문에 글자 수가 달라 보인다)
