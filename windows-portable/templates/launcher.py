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
    print(f"[Launcher] ⚠ Thư mục ứng dụng dài {len(str(ROOT))} ký tự — có thể vượt giới hạn 260 ký tự của Windows")
    if not os.environ.get("NO_BROWSER"):  # chế độ test tự động: không hiện dialog chặn luồng
        message_box(
            f"Thư mục ứng dụng đang nằm ở đường dẫn dài ({len(str(ROOT))} ký tự):\n{ROOT}\n\n"
            "Windows giới hạn đường dẫn 260 ký tự — một số file đính kèm có thể không mở được bằng "
            "Word/Excel.\n\nNên tắt app, chuyển cả thư mục sang đường dẫn ngắn như D:\\UdemyTranscript "
            "(dữ liệu đã tải đi theo thư mục). Thông báo này chỉ hiện 1 lần.", 0x40)
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
        print(f"[Launcher] NO_BROWSER — không mở trình duyệt (http://localhost:{port})")
        return
    webbrowser.open(f"http://localhost:{port}")


def _open_browser_when_ready(port: int, timeout_s: int = 30):
    for _ in range(timeout_s * 2):
        if is_our_instance(_app_info(port), DATA_DIR):
            open_browser(port)
            return
        time.sleep(0.5)
    print(f"[Launcher] ⚠ Server không sẵn sàng sau {timeout_s}s — không tự mở được trình duyệt.")
    message_box(f"Ứng dụng không khởi động được sau {timeout_s} giây.\n\nXem file app.log trong thư mục ứng dụng.")


def main():
    print(f"[Launcher] Khởi động {TITLE} (portable) — {ROOT}")
    running = find_running_instance()
    if running:
        print(f"[Launcher] Đang chạy sẵn trên port {running} — chỉ mở trình duyệt.")
        open_browser(running)
        return

    port = find_free_port()
    if port is None:
        msg = (f"Tất cả cổng từ {PORT_RANGE.start} đến {PORT_RANGE.stop - 1} đều đang bận.\n\n"
               "Hãy đóng bớt ứng dụng rồi chạy lại.")
        print(f"[Launcher] ⚠ {msg}")
        message_box(msg)
        return
    if port != PORT_PREFERRED:
        print(f"[Launcher] Port {PORT_PREFERRED} bận — dùng port {port}.")

    DATA_DIR.mkdir(exist_ok=True)
    warn_long_root()
    os.environ["PORTABLE_MODE"] = "true"
    os.environ.setdefault("DATA_DIR", str(DATA_DIR))
    os.chdir(APP_DIR)
    sys.path.insert(0, str(APP_DIR))

    threading.Thread(target=_open_browser_when_ready, args=(port,), daemon=True).start()

    import uvicorn
    from main import app
    print(f"[Launcher] Server: http://localhost:{port}  |  dữ liệu: {os.environ['DATA_DIR']}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        message_box("Ứng dụng gặp lỗi khi khởi động.\n\nXem chi tiết trong file app.log "
                    "(hoặc chạy start.bat để thấy log trực tiếp).", 0x10)
        raise
