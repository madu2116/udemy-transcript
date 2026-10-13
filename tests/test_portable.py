"""Bản Windows portable: app-info / shutdown / open-folder, bảo vệ Host + header, đường dẫn dài, launcher."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import main
from test_resources import ResClient, fake_file
from test_udemy import fake_vtt
from udemy import download_course

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows-portable" / "templates"))
import launcher  # noqa: E402

H = {"X-Requested-With": "udemy-transcript"}


@pytest.fixture
def api(data_dir):
    return TestClient(main.app)


@pytest.fixture
def portable(monkeypatch):
    monkeypatch.setattr(config, "PORTABLE", True)


# ── app-info ────────────────────────────────────────────────

def test_app_info_docker(api):
    assert api.get("/api/app-info").json() == {"app": "udemy-transcript", "portable": False, "data_dir": None}


def test_app_info_portable(api, portable, data_dir):
    info = api.get("/api/app-info").json()
    assert info["portable"] is True and info["data_dir"] == config.display_path(data_dir.resolve())
    assert not info["data_dir"].startswith("\\\\?\\")


# ── shutdown ────────────────────────────────────────────────

class FakeTimer:
    started = []

    def __init__(self, delay, fn):
        self.delay, self.fn = delay, fn

    def start(self):
        FakeTimer.started.append(self.delay)


def test_shutdown_requires_header(api, portable):
    assert api.post("/api/shutdown").status_code == 403


def test_shutdown_refused_in_docker(api):
    r = api.post("/api/shutdown", headers=H)
    assert r.status_code == 403 and "docker" in r.json()["detail"].lower()


def test_shutdown_portable(api, portable, monkeypatch):
    FakeTimer.started.clear()
    monkeypatch.setattr(main.threading, "Timer", FakeTimer)  # không os._exit thật
    assert api.post("/api/shutdown", headers=H).json() == {"ok": True}
    assert FakeTimer.started == [0.5]


# ── open-folder ─────────────────────────────────────────────

def test_open_folder_guards(api, monkeypatch):
    assert api.post("/api/open-folder").status_code == 403           # thiếu header
    assert api.post("/api/open-folder", headers=H).status_code == 403  # không phải portable


def test_open_folder_portable(api, portable, data_dir, monkeypatch):
    opened = []
    monkeypatch.setattr(main.os, "startfile", opened.append, raising=False)
    r = api.post("/api/open-folder", headers=H)
    assert r.status_code == 200 and opened == [config.display_path(config.COURSES_DIR)]
    assert config.COURSES_DIR.is_dir()
    assert api.post("/api/open-folder?slug=missing", headers=H).status_code == 404
    assert api.post("/api/open-folder?slug=..", headers=H).status_code == 404


# ── Host header (DNS rebinding) ─────────────────────────────

@pytest.mark.parametrize("host, ok", [("localhost", True), ("127.0.0.1", True), ("evil.example", False),
                                      ("localhost.evil.example", False)])
def test_trusted_host(data_dir, host, ok):
    client = TestClient(main.app, base_url=f"http://{host}")
    assert (client.get("/api/health").status_code == 200) is ok


def test_default_allowed_hosts_are_local_only(monkeypatch):
    import importlib
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    fresh = importlib.reload(config)
    try:
        assert fresh.ALLOWED_HOSTS == ["localhost", "127.0.0.1"]
    finally:
        monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
        importlib.reload(config)


# ── Đường dẫn dài trên Windows ──────────────────────────────

@pytest.mark.skipif(os.name != "nt", reason="tiền tố \\\\?\\ chỉ có trên Windows")
def test_long_path_windows(tmp_path):
    p = config.long_path(tmp_path)
    assert str(p).startswith("\\\\?\\") and config.long_path(p) == p
    assert config.display_path(p) == str(tmp_path.resolve())
    deep = p / ("d" * 120) / ("e" * 120) / ("f" * 60)  # > 260 ký tự
    deep.mkdir(parents=True)
    (deep / "x.txt").write_text("ok", encoding="utf-8")
    assert len(config.display_path(deep / "x.txt")) > 260 and (deep / "x.txt").read_text(encoding="utf-8") == "ok"


@pytest.mark.skipif(os.name == "nt", reason="Linux/Docker giữ nguyên đường dẫn")
def test_long_path_noop_elsewhere(tmp_path):
    assert config.long_path(tmp_path) == tmp_path


def test_display_path_variants():
    assert config.display_path("\\\\?\\D:\\a") == "D:\\a"
    assert config.display_path("\\\\?\\UNC\\srv\\share\\a") == "\\\\srv\\share\\a"
    assert config.display_path("/app/data") == "/app/data"


def test_resource_dir_error_is_not_fatal(tmp_path):
    """Hồi quy: lỗi tạo thư mục tài nguyên (vd WinError 206 đường dẫn quá dài) từng làm chết cả job."""
    res = tmp_path / "test-course" / "resources"
    res.mkdir(parents=True)
    (res / "01 Intro").write_text("không phải thư mục", encoding="utf-8")  # mkdir sẽ ném OSError
    logs = []
    meta = download_course("https://www.udemy.com/course/test-course/", "TOK", tmp_path, ["en"],
                           client_factory=ResClient, vtt_fetcher=fake_vtt, file_fetcher=fake_file, log=logs.append)
    assert meta["resources"]["failed"] == 3 and meta["resources"]["downloaded"] == 0
    assert meta["stats"]["en"]["downloaded"] == 1 and meta["html"] is True  # transcript + HTML vẫn xong
    assert any(line.startswith("[file] LỖI guide.pdf") for line in logs)


# ── launcher ────────────────────────────────────────────────

def test_launcher_is_our_instance(tmp_path):
    good = {"app": "udemy-transcript", "portable": True, "data_dir": str(tmp_path.resolve())}
    assert launcher.is_our_instance(good, tmp_path)
    assert launcher.is_our_instance({**good, "data_dir": "\\\\?\\" + str(tmp_path.resolve()).upper() + "\\"}, tmp_path)
    assert not launcher.is_our_instance({**good, "portable": False}, tmp_path)       # bản Docker
    assert not launcher.is_our_instance({**good, "data_dir": "C:\\other"}, tmp_path)  # bản giải nén khác
    assert not launcher.is_our_instance({**good, "app": "other-app"}, tmp_path)
    assert not launcher.is_our_instance(None, tmp_path) and not launcher.is_our_instance([], tmp_path)


def test_launcher_ports_avoid_docker():
    assert 8096 not in launcher.PORT_RANGE and launcher.PORT_PREFERRED == 8097


def test_launcher_long_root_warning_once(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(launcher, "message_box", lambda *a: shown.append(a))
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    monkeypatch.delenv("NO_BROWSER", raising=False)

    monkeypatch.setattr(launcher, "ROOT", Path("D:/UT"))
    launcher.warn_long_root()
    assert shown == [] and not (tmp_path / ".long-path-warned").exists()  # đường dẫn ngắn: không cảnh báo

    monkeypatch.setattr(launcher, "ROOT", Path("C:/Users/someone/Downloads/UdemyTranscript-v1.0-portable/UdemyTranscript"))
    launcher.warn_long_root()
    launcher.warn_long_root()
    assert len(shown) == 1 and (tmp_path / ".long-path-warned").exists()  # chỉ 1 lần


def test_launcher_no_dialog_in_test_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "message_box", lambda *a: pytest.fail("không được hiện dialog"))
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(launcher, "ROOT", Path("C:/" + "x" * 80))
    monkeypatch.setenv("NO_BROWSER", "1")
    launcher.warn_long_root()
    assert (tmp_path / ".long-path-warned").exists()


# ── build_portable: không phá bản portable đang chạy ────────

def _build_module():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows-portable"))
    import build_portable
    return build_portable


def test_build_stages_outside_dist():
    """Hồi quy: dựng gói ngay trong dist/ → user chạy thử từ đó → build sau xoá mất app/ của bản đang chạy."""
    bp = _build_module()
    assert bp.OUT.parent.name == "build" and bp.DIST not in bp.OUT.parents
    assert list(bp.PORTABLE_PORTS) == list(launcher.PORT_RANGE)


def test_find_running_build(tmp_path):
    bp = _build_module()
    out = tmp_path / "build" / "UdemyTranscript"
    infos = {8098: {"app": "udemy-transcript", "portable": True, "data_dir": str(out / "data").upper()},
             8097: {"app": "udemy-transcript", "portable": True, "data_dir": r"D:\elsewhere\data"}}
    assert bp.find_running_build(out, fetch=infos.get) == 8098
    assert bp.find_running_build(out, fetch={8097: infos[8097]}.get) is None  # bản chạy ở chỗ khác: không cản build
    assert bp.find_running_build(out, fetch=lambda p: {"app": "other", "data_dir": str(out)}) is None
    assert bp.find_running_build(out, fetch=lambda p: None) is None


def test_copy_app_does_not_delete_when_locked(tmp_path, monkeypatch):
    """Thư mục app/ bị khoá → dừng TRƯỚC khi xoá file nào (rename thất bại trước)."""
    bp = _build_module()
    out = tmp_path / "UdemyTranscript"
    (out / "app" / "static").mkdir(parents=True)
    (out / "app" / "main.py").write_text("old", encoding="utf-8")
    monkeypatch.setattr(bp, "OUT", out)
    real_rename = Path.rename

    def locked(self, target):
        if self.name == "app":
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real_rename(self, target)
    monkeypatch.setattr(Path, "rename", locked)
    with pytest.raises(SystemExit, match="đang bị dùng"):
        bp.copy_app()
    assert (out / "app" / "main.py").read_text(encoding="utf-8") == "old"  # không mất gì


def test_copy_app_replaces_cleanly(tmp_path, monkeypatch):
    bp = _build_module()
    out = tmp_path / "UdemyTranscript"
    (out / "app").mkdir(parents=True)
    (out / "app" / "stale.py").write_text("x", encoding="utf-8")
    monkeypatch.setattr(bp, "OUT", out)
    bp.copy_app()
    names = {p.name for p in (out / "app").iterdir()}
    assert "stale.py" not in names and set(bp.APP_FILES) <= names and "static" in names
    assert not (out / "app.old").exists()
