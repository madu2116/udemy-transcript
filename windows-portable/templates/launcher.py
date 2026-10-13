"""
launcher.py — khởi động bản Windows portable, KHÔNG hiện cửa sổ console.

UdemyTranscript.vbs chạy file này bằng runtime\\pythonw.exe; start.bat chạy bằng
runtime\\python.exe = chế độ debug (thấy log). Những điểm phải xử lý riêng:
  - pythonw trên máy thật có sys.stdout là TextIOWrapper cp1252 (KHÔNG phải None)
    → print tiếng Việt crash im lặng. Nhận diện bằng tên executable rồi redirect
    stdout/stderr ra app.log UTF-8.
  - Chỉ coi là "đang chạy sẵn" khi /api/app-info trả đúng app + đúng thư mục data
    (cổng bận bởi app khác, hay bản Docker ở 8096, không bị nhận nhầm).

Luồng: tìm phiên đang chạy → có thì chỉ mở browser; không thì tìm cổng trống
trong dải, chạy uvicorn trong process này với PORTABLE_MODE=true (bật nút
"Tắt ứng dụng" trên web), mở browser khi server trả lời được.
"""

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_DIR = ROOT / "app"
DATA_DIR = ROOT / "data"  # ngoài app/ → thay code bản mới không mất khoá đã tải
LOG = ROOT / "app.log"
APP_ID = "udemy-transcript"
TITLE = "Udemy Transcript"
PORT_PREFERRED = 8097  # bản Docker dùng 8096 — tránh đụng nhau khi chạy cùng máy
PORT_RANGE = range(PORT_PREFERRED, PORT_PREFERRED + 10)
# data\courses\<khoá ~60>\resources\<chương ~50>\<file ~100> ≈ 230 ký tự + thư mục cài đặt.
# Word/Excel/Explorer không mở được file > 260 ký tự (Python thì ghi được nhờ tiền tố \\?\).
LONG_ROOT_WARN = 40

_IS_PYTHONW = Path(sys.executable).name.lower() == "pythonw.exe"
if _IS_PYTHONW or sys.stdout is None or sys.stderr is None:
    _log_f = open(LOG, "w", encoding="utf-8", buffering=1)
    sys.stdout = _log_f
    sys.stderr = _log_f
else:
    try:  # console thật (start.bat) — ép UTF-8 phòng khi chcp 65001 không áp dụng
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# Launcher chạy TRƯỚC khi nạp app → bảng dịch riêng (app dùng i18n.py). Ngôn ngữ: lựa chọn đã lưu
# trong data/settings.json (nút EN|VI trên web) → ngôn ngữ giao diện Windows → tiếng Anh.
MESSAGES = {
    "starting": {"en": "[Launcher] Starting {title} (portable) — {root}",
                 "vi": "[Launcher] Khởi động {title} (portable) — {root}"},
    "running": {"en": "[Launcher] Already running on port {port} — just opening the browser.",
                "vi": "[Launcher] Đang chạy sẵn trên port {port} — chỉ mở trình duyệt."},
    "ports_busy": {"en": "All ports from {first} to {last} are busy.\n\nClose some applications and try again.",
                   "vi": "Tất cả cổng từ {first} đến {last} đều đang bận.\n\nHãy đóng bớt ứng dụng rồi chạy lại."},
    "port_fallback": {"en": "[Launcher] Port {preferred} busy — using port {port}.",
                      "vi": "[Launcher] Port {preferred} bận — dùng port {port}."},
    "server": {"en": "[Launcher] Server: http://localhost:{port}  |  data: {data}",
               "vi": "[Launcher] Server: http://localhost:{port}  |  dữ liệu: {data}"},
    "no_browser": {"en": "[Launcher] NO_BROWSER — not opening the browser (http://localhost:{port})",
                   "vi": "[Launcher] NO_BROWSER — không mở trình duyệt (http://localhost:{port})"},
    "not_ready_log": {"en": "[Launcher] ⚠ Server not ready after {s}s — could not open the browser.",
                      "vi": "[Launcher] ⚠ Server không sẵn sàng sau {s}s — không tự mở được trình duyệt."},
    "not_ready_box": {"en": "The app did not start within {s} seconds.\n\nSee app.log in the application folder.",
                      "vi": "Ứng dụng không khởi động được sau {s} giây.\n\nXem file app.log trong thư mục ứng dụng."},
    "long_log": {"en": "[Launcher] ⚠ Application folder path is {n} characters long — may exceed Windows' 260-character limit",
                 "vi": "[Launcher] ⚠ Thư mục ứng dụng dài {n} ký tự — có thể vượt giới hạn 260 ký tự của Windows"},
    "long_box": {
        "en": "The application folder is in a long path ({n} characters):\n{root}\n\n"
              "Windows limits paths to 260 characters — some attached files may not open in Word/Excel.\n\n"
              "Quit the app and move the whole folder to a short path such as D:\\UdemyTranscript "
              "(downloaded data moves with it). This message is shown only once.",
        "vi": "Thư mục ứng dụng đang nằm ở đường dẫn dài ({n} ký tự):\n{root}\n\n"
              "Windows giới hạn đường dẫn 260 ký tự — một số file đính kèm có thể không mở được bằng "
              "Word/Excel.\n\nNên tắt app, chuyển cả thư mục sang đường dẫn ngắn như D:\\UdemyTranscript "
              "(dữ liệu đã tải đi theo thư mục). Thông báo này chỉ hiện 1 lần."},
    "crash_box": {"en": "The app hit an error while starting.\n\nSee app.log for details "
                        "(or run start.bat to see the log live).",
                  "vi": "Ứng dụng gặp lỗi khi khởi động.\n\nXem chi tiết trong file app.log "
                        "(hoặc chạy start.bat để thấy log trực tiếp)."},
}
LANG_VI_PRIMARY = 0x2A  # PRIMARYLANGID của tiếng Việt (LANGID 0x042A)


def detect_lang() -> str:
    try:
        import json
        lang = json.loads((DATA_DIR / "settings.json").read_text(encoding="utf-8")).get("ui_lang")
        if lang in ("en", "vi"):
            return lang
    except (OSError, ValueError, AttributeError):
        pass
    try:
        import ctypes
        if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == LANG_VI_PRIMARY:
            return "vi"
    except Exception:  # không phải Windows
        pass
    return "en"


LANG = "en"


def msg(key: str, **kw) -> str:
    entry = MESSAGES[key]
    return (entry.get(LANG) or entry["en"]).format(**kw)


def message_box(text: str, icon: int = 0x30):
    """Hộp thoại Windows — cách duy nhất báo lỗi cho user khi chạy pythonw (không console)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, TITLE, icon)
    except Exception:
        pass


def _norm(path) -> str:
    s = str(path)
    return (s[4:] if s.startswith("\\\\?\\") else s).rstrip("\\/").lower()


def is_our_instance(info, data_dir: Path) -> bool:
    return (isinstance(info, dict) and info.get("app") == APP_ID and info.get("portable") is True
            and _norm(info.get("data_dir") or "") == _norm(data_dir.resolve()))


def warn_long_root():
    """Cảnh báo 1 lần cho mỗi thư mục cài đặt (đánh dấu bằng file trong data/)."""
    marker = DATA_DIR / ".long-path-warned"
    if len(str(ROOT)) <= LONG_ROOT_WARN or marker.exists():
        return
    print(msg("long_log", n=len(str(ROOT))))
    if not os.environ.get("NO_BROWSER"):  # chế độ test tự động: không hiện dialog chặn luồng
        message_box(msg("long_box", n=len(str(ROOT)), root=ROOT), 0x40)
    try:
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass


def _is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _app_info(port: int):
    try:
        import json
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/app-info", timeout=2) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def find_running_instance() -> int | None:
    for port in PORT_RANGE:
        if _is_port_open(port) and is_our_instance(_app_info(port), DATA_DIR):
            return port
    return None


def find_free_port() -> int | None:
    for port in PORT_RANGE:
        if not _is_port_open(port):
            return port
    return None


def open_browser(port: int):
    if os.environ.get("NO_BROWSER"):  # test tự động: không mở browser, không hiện dialog
        print(msg("no_browser", port=port))
        return
    webbrowser.open(f"http://localhost:{port}")


def _open_browser_when_ready(port: int, timeout_s: int = 30):
    for _ in range(timeout_s * 2):
        if is_our_instance(_app_info(port), DATA_DIR):
            open_browser(port)
            return
        time.sleep(0.5)
    print(msg("not_ready_log", s=timeout_s))
    message_box(msg("not_ready_box", s=timeout_s))


def main():
    global LANG
    LANG = detect_lang()
    # App chưa có settings.json (lần đầu) → mặc định theo ngôn ngữ Windows; web UI vẫn đổi được
    os.environ.setdefault("APP_LANG", LANG)
    print(msg("starting", title=TITLE, root=ROOT))
    running = find_running_instance()
    if running:
        print(msg("running", port=running))
        open_browser(running)
        return

    port = find_free_port()
    if port is None:
        text = msg("ports_busy", first=PORT_RANGE.start, last=PORT_RANGE.stop - 1)
        print(f"[Launcher] ⚠ {text}")
        message_box(text)
        return
    if port != PORT_PREFERRED:
        print(msg("port_fallback", preferred=PORT_PREFERRED, port=port))

    DATA_DIR.mkdir(exist_ok=True)
    warn_long_root()
    os.environ["PORTABLE_MODE"] = "true"
    os.environ.setdefault("DATA_DIR", str(DATA_DIR))
    os.chdir(APP_DIR)
    sys.path.insert(0, str(APP_DIR))

    threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()

    import uvicorn
    from main import app
    print(msg("server", port=port, data=os.environ["DATA_DIR"]))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        message_box(msg("crash_box"), 0x10)
        raise
