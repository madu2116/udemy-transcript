import os
from pathlib import Path

_LONG_PREFIX = "\\\\?\\"


def long_path(p: Path) -> Path:
    r"""Windows: thêm tiền tố \\?\ để vượt giới hạn MAX_PATH 260 ký tự (đường dẫn con kế thừa
    tiền tố). Bản portable giải nén vào thư mục sâu (Downloads\...) + tên khoá/chương/file dài
    là vượt 260 ngay — đã gặp thật lúc test. Linux/Docker giữ nguyên."""
    if os.name != "nt":
        return p
    s = str(Path(p).resolve())
    if s.startswith(_LONG_PREFIX):
        return Path(s)
    return Path(_LONG_PREFIX + "UNC\\" + s[2:] if s.startswith("\\\\") else _LONG_PREFIX + s)


def display_path(p) -> str:
    r"""Bỏ tiền tố \\?\ khi hiện cho người dùng / gọi Explorer."""
    s = str(p)
    if s.startswith(_LONG_PREFIX + "UNC\\"):
        return "\\\\" + s[len(_LONG_PREFIX) + 4:]
    return s[len(_LONG_PREFIX):] if s.startswith(_LONG_PREFIX) else s


DATA_DIR = long_path(Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data")))
COURSES_DIR = DATA_DIR / "courses"
TOKEN_FILE = DATA_DIR / "token.txt"
DEFAULT_LANGS = [x.strip().lower() for x in os.environ.get("TRANSCRIPT_LANGS", "en,vi").split(",") if x.strip()]
WORKERS = int(os.environ.get("TRANSCRIPT_WORKERS", "4"))
# Bản Windows portable (launcher.py đặt) — bật nút tắt app / mở thư mục trên UI
PORTABLE = os.environ.get("PORTABLE_MODE", "").lower() == "true"
# Host header hợp lệ — chặn DNS rebinding (trang web lạ trỏ domain về 127.0.0.1 để gọi API)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]


def load_token() -> tuple[str, str]:
    """Trả (token, nguồn). Token dán qua web UI (lưu trong data/) được ưu tiên
    hơn .env vì đó là cách cập nhật khi token hết hạn mà không cần recreate container."""
    if TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if tok:
            return tok, "web"
    tok = os.environ.get("UDEMY_ACCESS_TOKEN", "").strip()
    return (tok, "env") if tok else ("", "none")


def save_token(raw: str):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(raw.strip(), encoding="utf-8")


def clear_token():
    TOKEN_FILE.unlink(missing_ok=True)
