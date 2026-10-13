"""Đa ngôn ngữ giao diện EN/VI: bảng dịch, chọn/lưu ngôn ngữ, API settings, nội dung sinh ra bằng tiếng Anh."""
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import i18n
import main
import render
from i18n import MESSAGES, placeholders, t
from test_overview import FULL_DETAILS, DetailClient
from test_resources import ResClient, fake_file
from test_udemy import fake_vtt
from udemy import download_course

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "windows-portable" / "templates"))
import launcher  # noqa: E402

VI_CHARS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


# ── Bảng dịch ───────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_every_message_has_both_langs_with_same_placeholders(key):
    entry = MESSAGES[key]
    assert set(entry) == {"en", "vi"}, key
    assert entry["en"].strip() and entry["vi"].strip()
    assert placeholders(entry["en"]) == placeholders(entry["vi"]), key
    assert not VI_CHARS.search(entry["en"]), f"{key}: bản en còn chữ tiếng Việt"


def test_t_formats_and_falls_back():
    assert t("log_course", ui_lang="en", id=5, title="X") == "Course #5: X"
    assert t("log_course", ui_lang="vi", id=5, title="X") == "Khoá #5: X"
    assert t("ov_link", ui_lang="xx") == "Link"  # ngôn ngữ lạ → tiếng Anh
    with pytest.raises(KeyError):
        t("no_such_key")


def test_caption_lang_placeholder_is_not_ui_lang():
    """Hồi quy: t() từng có tham số tên `lang` → t("log_captions", lang="en") bị hiểu là ngôn ngữ
    giao diện, placeholder {lang} (mã ngôn ngữ PHỤ ĐỀ) trống → KeyError giữa job."""
    out = t("log_captions", ui_lang="vi", lang="en", available=1, total=2, auto=0, skipped=0)
    assert out.startswith("[en] có phụ đề 1/2 bài")
    assert "lang" in placeholders(MESSAGES["log_captions"]["en"])


# ── Chọn & lưu ngôn ngữ ─────────────────────────────────────

def test_lang_precedence(monkeypatch):
    monkeypatch.delenv("APP_LANG", raising=False)
    assert i18n.saved_lang() is None and i18n.get_lang() == "en"   # mặc định
    monkeypatch.setenv("APP_LANG", "VI")
    assert i18n.get_lang() == "vi"                                  # biến môi trường
    monkeypatch.setenv("APP_LANG", "fr")
    assert i18n.get_lang() == "en"                                  # không hỗ trợ → mặc định
    i18n.set_lang("vi")
    monkeypatch.setenv("APP_LANG", "en")
    assert i18n.saved_lang() == "vi" and i18n.get_lang() == "vi"    # lựa chọn đã lưu thắng env


def test_set_lang_persists_and_keeps_other_settings(monkeypatch):
    path = config.DATA_DIR / "settings.json"
    path.write_text(json.dumps({"other": 1}), encoding="utf-8")
    i18n.set_lang("en")
    assert json.loads(path.read_text(encoding="utf-8")) == {"other": 1, "ui_lang": "en"}
    monkeypatch.setattr(i18n, "_cache", {})  # đọc lại từ đĩa như lúc khởi động
    assert i18n.saved_lang() == "en"
    with pytest.raises(ValueError):
        i18n.set_lang("fr")


@pytest.mark.parametrize("content", ["{bad json", '["list"]', '{"ui_lang": "fr"}', '{"ui_lang": 1}'])
def test_corrupt_settings_ignored(content):
    (config.DATA_DIR / "settings.json").write_text(content, encoding="utf-8")
    assert i18n.saved_lang() is None and i18n.get_lang() == "vi"  # conftest đặt APP_LANG=vi


# ── API /api/settings ───────────────────────────────────────

@pytest.fixture
def api(data_dir):
    return TestClient(main.app)


def test_settings_api(api):
    assert api.get("/api/settings").json() == {"ui_lang": "vi", "saved": False, "langs": ["en", "vi"]}
    r = api.post("/api/settings", json={"ui_lang": "EN"})
    assert r.status_code == 200 and r.json()["ui_lang"] == "en" and r.json()["saved"] is True
    assert api.get("/api/settings").json()["ui_lang"] == "en"
    r = api.post("/api/settings", json={"ui_lang": "fr"})
    assert r.status_code == 400 and r.json()["detail"] == "Unsupported interface language (en, vi)"  # lỗi theo ngôn ngữ đang chọn


def test_api_errors_follow_ui_lang(api):
    assert api.get("/api/jobs/nope").json()["detail"] == "Không có job này"
    api.post("/api/settings", json={"ui_lang": "en"})
    assert api.get("/api/jobs/nope").json()["detail"] == "No such job"
    assert api.post("/api/jobs", json={"url": "https://evil.com/course/x/"}).json()["detail"] == "Not a udemy.com URL"


def test_switching_lang_rerenders_downloaded_courses(api, data_dir):
    download_course("https://www.udemy.com/course/test-course/", "TOK", config.COURSES_DIR, ["en"],
                    client_factory=DetailClient, vtt_fetcher=fake_vtt, log=lambda m: None)
    d = config.COURSES_DIR / "test-course"
    assert "## Bạn sẽ học được gì" in (d / "OVERVIEW.md").read_text(encoding="utf-8")
    assert '<html lang="vi">' in (d / "index.html").read_text(encoding="utf-8")

    r = api.post("/api/settings", json={"ui_lang": "en"})
    assert r.json()["rerendered"] == 1
    assert "## What you'll learn" in (d / "OVERVIEW.md").read_text(encoding="utf-8")  # dựng lại từ overview.json
    index = (d / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in index and "Course overview" in index and "Tổng quan khoá" not in index
    transcript = (d / "transcript.en.html").read_text(encoding="utf-8")
    assert "Contents · 2 lectures" in transcript and "<h1>Transcript · English</h1>" in transcript

    assert api.post("/api/settings", json={"ui_lang": "en"}).json()["rerendered"] == 0  # không đổi → không dựng lại


def test_rerender_skips_broken_course(api, data_dir):
    bad = config.COURSES_DIR / "broken"
    bad.mkdir(parents=True)
    (bad / "course.json").write_text("{not json", encoding="utf-8")
    assert api.post("/api/settings", json={"ui_lang": "en"}).status_code == 200


# ── Nội dung sinh ra bằng tiếng Anh ─────────────────────────

def test_download_course_in_english(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_LANG", "en")
    logs = []
    meta = download_course("https://www.udemy.com/course/test-course/", "TOK", tmp_path, ["en"],
                           client_factory=ResClient, vtt_fetcher=fake_vtt, file_fetcher=fake_file, log=logs.append)
    d = tmp_path / "test-course"
    assert logs[0] == "Looking up course 'test-course' on www.udemy.com..."
    assert "[en] done: downloaded 1, skipped 0, failed 0, no captions 0" in logs
    assert "[file] ERROR broken.docx: Udemy returned no download link for this file" in logs
    assert not any(VI_CHARS.search(line) for line in logs), [l for l in logs if VI_CHARS.search(l)]

    index_md = (d / "resources" / "INDEX.md").read_text(encoding="utf-8")
    assert index_md.startswith("# Test Course — attached resources") and "— *not downloaded*" in index_md
    html = (d / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html and "1 sections · 1 video lectures · 3 attached files" in html
    assert '<span class="side">Article</span>' in html and "broken.docx — not downloaded" in html
    assert meta["html"] is True


def test_overview_in_english(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_LANG", "en")
    download_course("https://www.udemy.com/course/test-course/", "TOK", tmp_path, ["en"],
                    client_factory=DetailClient, vtt_fetcher=fake_vtt, log=lambda m: None)
    md = (tmp_path / "test-course" / "OVERVIEW.md").read_text(encoding="utf-8")
    for line in ["- **Instructors:** Jane Doe (Coach), Bob", "- **Length:** 4.5 total hours · 71 lectures",
                 "- **Rating:** 4.5/5 (3,065 ratings) · 12,794 students", "- **Last updated:** 2024-01-02",
                 "## What you'll learn", "## Requirements", "## Description", "## Who this course is for"]:
        assert line in md
    assert not VI_CHARS.search(md.replace(FULL_DETAILS["title"], ""))
    overview_html = render.render_overview({"title": "T"}, md)
    assert '<a href="index.html">← Course home</a>' in overview_html and "<title>Overview — T</title>" in overview_html


# ── Web UI (static/index.html) ──────────────────────────────

def _ui_dicts():
    src = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    block = src[src.index("const STR = {"):src.index("\n};", src.index("const STR = {"))]
    en, vi = block.split("\n  vi: {")
    keys = lambda part: set(re.findall(r"(?:^|,)\s*(\w+):\s*[\"'`]", part, re.M))
    return src, keys(en.split("en: {", 1)[1]), keys(vi)


def test_ui_dicts_have_same_keys():
    _, en, vi = _ui_dicts()
    assert len(en) > 40 and en == vi, en ^ vi


def test_ui_every_used_key_is_defined():
    src, en, _ = _ui_dicts()
    used = set(re.findall(r'data-i18n(?:-html|-ph|-title)?="(\w+)"', src))
    used |= set(re.findall(r'\bT\("(\w+)"', src))
    used |= {f"job_{s}" for s in ("queued", "running", "done", "error")}  # T(`job_${job.status}`)
    assert used <= en, used - en


def test_ui_has_lang_switch_and_settings_calls():
    src, _, _ = _ui_dicts()
    assert 'data-ui-lang="en"' in src and 'data-ui-lang="vi"' in src
    assert "/api/settings" in src and "navigator.language" in src


# ── Launcher portable ───────────────────────────────────────

@pytest.mark.parametrize("key", sorted(launcher.MESSAGES))
def test_launcher_messages(key):
    entry = launcher.MESSAGES[key]
    assert set(entry) == {"en", "vi"} and placeholders(entry["en"]) == placeholders(entry["vi"])
    assert not VI_CHARS.search(entry["en"])


def test_launcher_detect_lang(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "DATA_DIR", tmp_path)
    (tmp_path / "settings.json").write_text('{"ui_lang": "vi"}', encoding="utf-8")
    assert launcher.detect_lang() == "vi"
    (tmp_path / "settings.json").write_text('{"ui_lang": "en"}', encoding="utf-8")
    assert launcher.detect_lang() == "en"
    (tmp_path / "settings.json").write_text("{bad", encoding="utf-8")
    assert launcher.detect_lang() in ("en", "vi")  # rơi về ngôn ngữ Windows, không crash


def test_launcher_msg_uses_current_lang(monkeypatch):
    monkeypatch.setattr(launcher, "LANG", "en")
    assert launcher.msg("running", port=8097).startswith("[Launcher] Already running on port 8097")
    monkeypatch.setattr(launcher, "LANG", "vi")
    assert launcher.msg("running", port=8097).startswith("[Launcher] Đang chạy sẵn trên port 8097")


# ── Gói portable ────────────────────────────────────────────

def test_portable_bundles_every_app_module():
    """Hồi quy: i18n.py suýt không được copy vào gói → bản portable crash lúc khởi động."""
    sys.path.insert(0, str(ROOT / "windows-portable"))
    import build_portable
    modules = {p.name for p in ROOT.glob("*.py")}
    assert modules == set(build_portable.APP_FILES), modules ^ set(build_portable.APP_FILES)
    for f in ("README_USER.txt", "README_USER.vi.txt"):
        assert f in build_portable.LAUNCHER_FILES and (ROOT / "windows-portable" / "templates" / f).exists()


def test_language_labels_follow_ui_but_switch_keeps_endonyms(tmp_path, monkeypatch):
    """Trong câu chữ: tên ngôn ngữ dịch theo giao diện ("Transcript Vietnamese"). Nút chuyển ngôn ngữ
    trên trang transcript: giữ tên gốc ("Tiếng Việt") như mọi language switcher."""
    from test_render import make_meta
    monkeypatch.setenv("APP_LANG", "en")
    index = render.render_index(make_meta(), None, has_overview=False)
    assert ">Transcript English</a>" in index and ">Transcript Vietnamese (machine-translated)</a>" in index
    course = tmp_path / "c"
    (course / "en").mkdir(parents=True)
    (course / "en" / "01.01 Hello.txt").write_text("Hi.", encoding="utf-8")
    doc = render.render_transcript(make_meta(), course, "en")
    assert "<h1>Transcript · English</h1>" in doc and "<title>Transcript English — " in doc
    assert '<a href="transcript.vi.html" data-keep-hash>Tiếng Việt</a>' in doc
