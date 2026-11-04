윈도우에서 CapCut 기능을 조사할 때는 프로그램을 띄우지 말고 **화면 글자 번역표(`Resources/po/ko-KR.po`)와 사용자 프로젝트 파일(`draft_content.json`)** 을 읽어라. REA 의 "실행 중인 창 관찰"은 맥 전용이라 윈도우에서 돌지 않는다.

상황 (2026-11-04): 지인 의견("끌어서 늘이고 줄이는 기능")을 받아 CapCut 9.2 와 비교하려고 REA 를 썼다.
`binary_session` 으로 보니 `observe_native_ui`·`capture_native_ui_scenario` 는 `unsupported_host`(맥 전용)였다.
CapCut 화면은 Qt6(QML) + 바이트댄스 Lynx + CEF 로 되어 있어 JS 묶음 분석으로도 타임라인 동작이 안 나온다.

통한 방법:
- 설치 위치: `%LOCALAPPDATA%\CapCut\Apps\<판번호>\` (판이 여럿 깔려 있으면 가장 높은 번호)
- `Resources\po\ko-KR.po` 에 화면 글자 1만 5천여 개가 `msgid`(내부 이름)·`msgstr`(한국어)로 들어 있다.
  내부 이름에 `magnet`, `snap`, `preview_axis`, `track`, `freeze`, `shortcut` 을 찾으면 타임라인 기능 목록이 나온다
- 프로젝트: `%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft\<이름>\draft_content.json` 은 암호화되지 않은 JSON 이다.
  조각마다 `target_timerange`(타임라인 위 자리)와 `source_timerange`(원본에서 쓰는 부분)가 백만분의 1초 단위로 있다
- 단축키 배정은 프로그램 안에 박혀 있다. `User Data\Config\keymapSettings` 에는 배정표 번호만 있다

함정:
- po 파일을 파이썬으로 읽어 print 하면 Bash 창에서 한글이 깨진다. **UTF-8 파일로 써서 Read 로 읽어라** ([[windows-console-encoding]])
- CapCut 을 띄워 사용자 프로젝트를 열면 자동 저장으로 파일이 바뀔 수 있다. 읽기만 할 거면 띄우지 마라

중요한 이유: 이 길을 모르면 도구 설정과 맥 전용 기능에서 시간을 다 쓴다. 결과는 `docs/REVIEW_timeline_usability.md` 에 있다.
