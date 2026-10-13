import os
import sys
from pathlib import Path

# TestClient gửi Host: testserver — phải đặt trước khi import config/main
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_ui_lang(tmp_path_factory, monkeypatch):
    """Mọi test chạy ở giao diện tiếng Việt (assertion cũ viết theo tiếng Việt) và có settings.json
    riêng — không đọc nhầm data/settings.json thật mà bản Docker (mount cùng thư mục) ghi ra."""
    import i18n
    monkeypatch.setattr(config, "DATA_DIR", tmp_path_factory.mktemp("settings"))
    monkeypatch.setenv("APP_LANG", "vi")
    monkeypatch.setattr(i18n, "_cache", {})


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "COURSES_DIR", tmp_path / "courses")
    monkeypatch.setattr(config, "TOKEN_FILE", tmp_path / "token.txt")
    monkeypatch.delenv("UDEMY_ACCESS_TOKEN", raising=False)
    return tmp_path
