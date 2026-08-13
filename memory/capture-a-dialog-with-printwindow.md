설치 창처럼 **다른 창 뒤에 가려지는 창**은 화면 전체를 찍어서는 안 잡힌다. 창 자체의 그림을 뽑는 `PrintWindow` 로 찍어야 하고, 화면 배율 때문에 **창이 알려 주는 크기보다 넉넉하게** 잡아야 잘리지 않는다.

무슨 일이 있었나 (2026-08-13):
"프로그램을 켜 둔 채 설치하면 한국어 안내 창이 뜨는가"를 **눈으로** 확인해야 했다.

1. **화면 전체를 찍었다** → 안내 창이 없었다. 창 목록에는 분명히
   `#32770 "Setup" 471×248` 이 있었는데도 그렇다. 브라우저 창이 그 위를 덮고 있었고,
   화면 캡처는 **합쳐진 결과**만 찍기 때문이다. 창이 "보이는 상태(IsWindowVisible=True)"라는
   것과 "화면에서 보인다"는 것은 다른 말이다.
2. **앞으로 불러내려 했다** (`SetForegroundWindow`) → 그 자리에 바탕화면만 찍혔고,
   그다음 확인해 보니 창이 아예 숨은 상태가 되어 있었다. 남의 프로세스 창을 앞으로 끌어내는
   것은 윈도우가 막는 경우가 많다. **믿을 수 없는 방법이다.**
3. **통한 방법 — `PrintWindow`**: 창에게 "네 그림을 이 도화지에 그려라"라고 시킨다.
   z-순서와 무관하고, 가려져 있어도 온전히 나온다.

```powershell
Add-Type @"
using System;using System.Runtime.InteropServices;
public class U { [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f); }
"@
Add-Type -AssemblyName System.Drawing
$bmp = New-Object System.Drawing.Bitmap(1100, 620)     # 넉넉하게
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::Magenta)              # 남는 자리를 눈에 띄는 색으로
$hdc = $g.GetHdc(); [void][U]::PrintWindow($h, $hdc, 2); $g.ReleaseHdc($hdc); $g.Dispose()
$bmp.Save($경로, [System.Drawing.Imaging.ImageFormat]::Png)
```

마지막 인자 `2` 는 `PW_RENDERFULLCONTENT` 다. 이것이 없으면 요즘 방식으로 그리는 창이
**빈 그림**으로 나온다.

### 크기를 창이 말한 대로 잡으면 잘린다

`GetWindowRect` 는 471×248 이라고 했는데 실제 그림은 그보다 컸다. 화면 배율(DPI)이
100%가 아닌데 PowerShell 이 배율을 모르는 상태로 도는 탓이다. 처음에 471×248 도화지에
그렸더니 **오른쪽 글자와 아래 단추가 통째로 잘려** 나갔다 — 그런데 잘린 그림도 "안내 창이
떴다"는 것은 보여 주므로, **다 확인했다고 착각하기 쉽다.** 넉넉히 잡고 남는 자리를
마젠타로 칠해 두면 창의 경계가 어디까지인지 한눈에 보인다.

### 창 찾는 법

`EnumWindows` 로 그 프로세스의 창을 전부 훑고 클래스 이름을 본다. 윈도우 표준 대화상자는
클래스가 **`#32770`** 이다. 설치 프로그램은 실행 파일 두 개(`...-Setup.exe` 와
`...-Setup.tmp`)로 도니 **둘 다** 대상에 넣어야 한다.

왜 중요한가: 이 프로젝트는 "코드가 그렇게 되어 있다"가 아니라 **사람 눈에 보이는 것**으로
판정한다([[verify-ui-by-actually-clicking]]). 화면 안쪽은 Playwright 로 보지만, 설치 창처럼
**브라우저 밖에 있는 창**은 이 방법이 유일하다. 배포 전 마지막 확인에서 다시 쓰게 된다.
