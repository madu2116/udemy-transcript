"""Dựng HTML đọc trên trình duyệt (render.py) + route /view."""
import json
import re

import pytest
from fastapi.testclient import TestClient

import config
import main
import render
from test_resources import ResClient, fake_file
from test_udemy import FakeClient, cap, chapter_item, fake_vtt, lecture_item
from udemy import download_course

EVIL = '<script>alert(1)</script><img src=x onerror=alert(2)>'


def make_meta(**over):
    meta = {
        "title": "Course " + EVIL, "slug": "c", "url": "https://www.udemy.com/course/c/",
        "langs": ["en", "vi"], "combined": {"en": 2, "vi": 1}, "chapter_count": 2, "lecture_count": 2,
        "stats": {"en": {"available": 2, "auto": 0}, "vi": {"available": 1, "auto": 1}},
        "outline": [
            {"index": 1, "title": "Intro", "lectures": [
                {"id": 1, "title": "Hello " + EVIL, "kind": "video", "number": "01.01", "stem": "01.01 Hello",
                 "duration": 125, "captions": {"en": "manual", "vi": "auto"}, "transcripts": {"en": True, "vi": True},
                 "resources": [{"kind": "file", "name": "a b.pdf", "path": "resources/01 Intro/a b.pdf", "ok": True},
                               {"kind": "file", "name": "gone.docx", "path": "resources/01 Intro/gone.docx", "ok": False},
                               {"kind": "link", "name": "Site", "url": "https://x.y/?a=1&b=2"}]},
                {"id": 2, "title": "Reading", "kind": "article", "resources": []},
            ]},
            {"index": 2, "title": "Deep", "lectures": [
                {"id": 3, "title": "Second", "kind": "video", "number": "02.01", "stem": "02.01 Second",
                 "duration": 60, "captions": {"en": "manual", "vi": None}, "transcripts": {"en": True, "vi": False},
                 "resources": []},
            ]},
        ],
    }
    meta.update(over)
    return meta


@pytest.fixture
def course(tmp_path):
    d = tmp_path / "c"
    for lang, stems in {"en": ["01.01 Hello", "02.01 Second"], "vi": ["01.01 Hello"]}.items():
        (d / lang).mkdir(parents=True)
        for s in stems:
            (d / lang / f"{s}.txt").write_text(f"First para {lang} {s} {EVIL}.\n\nSecond   para.", encoding="utf-8")
    return d


def no_raw_evil(doc: str):
    assert "<script>alert" not in doc and "<img src=x" not in doc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in doc


# ── helpers ─────────────────────────────────────────────────

def test_anchor_and_helpers():
    assert render.anchor("01.02") == "l-01-02"
    assert render.fmt_duration(125) == "2:05" and render.fmt_duration(None) == "0:00"
    assert render.lang_name("vi") == "Tiếng Việt" and render.lang_name("xx") == "XX"
    assert render.lang_label("en") == "Tiếng Anh" and render.lang_label("xx") == "XX"  # giao diện vi (conftest)
    assert render.chapter_heading({"index": 0, "title": ""}) == "Mở đầu"


# ── transcript.<lang>.html ──────────────────────────────────

def test_transcript_page(course):
    doc = render.render_transcript(make_meta(), course, "en")
    no_raw_evil(doc)
    assert doc.startswith("<!doctype html>")
    assert '<article id="l-01-01">' in doc and '<article id="l-02-01">' in doc
    assert '<a href="#l-01-01"><span class="num">01.01</span>Hello &lt;script&gt;' in doc
    assert "<p>Second para.</p>" in doc  # gộp khoảng trắng, tách đoạn theo dòng trống
    assert '<a href="transcript.vi.html" data-keep-hash>Tiếng Việt</a>' in doc
    assert '<span class="on">English</span>' in doc
    assert "Mục lục · 2 bài" in doc and "dịch máy</b>" not in doc
    assert '<a class="res" href="resources/01 Intro/a b.pdf">📎 a b.pdf</a>' in doc
    assert "gone.docx — chưa tải được" in doc
    assert 'href="https://x.y/?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">🔗 Site' in doc
    assert "<script>\n(function(){" in doc  # JS mục lục/đổi ngôn ngữ


def test_transcript_page_all_auto_lang(course):
    doc = render.render_transcript(make_meta(), course, "vi")
    assert "Mục lục · 1 bài" in doc and 'id="l-02-01"' not in doc  # bài không có transcript vi bị bỏ
    assert "dịch máy</b>" in doc and '<span class="badge auto">dịch máy</span>' in doc
    assert 'id="c-02"' not in doc  # chương không còn bài nào thì không hiện


def test_transcript_page_single_lang_has_no_switch(course):
    meta = make_meta(langs=["en"], combined={"en": 2})
    doc = render.render_transcript(meta, course, "en")
    assert "data-keep-hash>" not in doc and 'class="seg"' not in doc  # JS dùng chung vẫn có chuỗi selector


def test_transcript_page_none_when_empty(tmp_path):
    assert render.render_transcript(make_meta(), tmp_path, "en") is None


# ── index.html ──────────────────────────────────────────────

def test_index_page():
    details = {"headline": "Head " + EVIL, "visible_instructors": [{"display_name": "Jane"}],
               "content_info": "4.5 total hours", "instructional_level_simple": "All Levels",
               "last_update_date": "2024-01-02"}
    doc = render.render_index(make_meta(), details, has_overview=True)
    no_raw_evil(doc)
    assert '<p class="headline">Head &lt;script&gt;' in doc
    for fact in ("👤 Jane", "⏱ 4.5 total hours", "📶 All Levels", "🗓 Cập nhật 2024-01-02", "2 chương · 2 bài video · 2 file đính kèm"):
        assert fact in doc
    assert '<a class="btn" href="overview.html">' in doc
    assert '<a class="btn primary" href="transcript.en.html">Transcript Tiếng Anh</a>' in doc
    assert '<a class="btn" href="transcript.vi.html">Transcript Tiếng Việt (dịch máy)</a>' in doc
    assert '<a class="chip" title="phụ đề gốc" href="transcript.en.html#l-01-01">EN</a>' in doc
    assert '<a class="chip auto" title="phụ đề dịch máy" href="transcript.vi.html#l-01-01">VI</a>' in doc
    assert '<span class="chip off" title="không có phụ đề">VI</span>' in doc  # bài 02.01
    assert '<span class="side">Bài đọc</span>' in doc  # bài article vẫn hiện trong mục lục


def test_index_page_without_overview_or_details():
    doc = render.render_index(make_meta(), None, has_overview=False)
    assert "overview.html" not in doc and 'class="headline"' not in doc


# ── overview.html ───────────────────────────────────────────

def test_overview_page_escapes_raw_html_and_blocks_js_links():
    md = f"# Title\n\n> Head\n\n- **Giảng viên:** Jane\n\n## Mô tả\n\n{EVIL}\n\n[bad](javascript:alert(3)) [ok](https://ok.example)\n"
    doc = render.render_overview(make_meta(), md)
    no_raw_evil(doc)
    assert 'href="javascript:' not in doc
    assert '<a href="https://ok.example">ok</a>' in doc
    assert "<h1>Title</h1>" in doc and "<blockquote>" in doc and "<strong>Giảng viên:</strong>" in doc
    assert '<a href="index.html">← Trang khoá</a>' in doc


# ── render_course ───────────────────────────────────────────

def test_render_course_writes_and_cleans(course):
    (course / "OVERVIEW.md").write_text("# T\n", encoding="utf-8")
    (course / "overview.json").write_text("{bad json", encoding="utf-8")  # hỏng → bỏ qua, không lỗi
    (course / "transcript.ja.html").write_text("stale", encoding="utf-8")
    meta = make_meta(langs=["en", "vi", "ja"])
    (course / "course.json").write_text(json.dumps(meta), encoding="utf-8")
    assert render.render_course(course) == ["overview.html", "transcript.en.html", "transcript.vi.html", "index.html"]
    assert not (course / "transcript.ja.html").exists()


def test_render_course_requires_outline(tmp_path):
    (tmp_path / "course.json").write_text(json.dumps({"title": "old"}), encoding="utf-8")
    with pytest.raises(ValueError, match="outline"):
        render.render_course(tmp_path)


def test_render_cli(course, capsys):
    (course / "course.json").write_text(json.dumps(make_meta()), encoding="utf-8")
    assert render.main([str(course)]) == 0
    assert "c: transcript.en.html" in capsys.readouterr().out
    assert render.main([str(course.parent / "missing")]) == 1
    assert render.main([]) == 2


# ── end-to-end qua download_course ──────────────────────────

def test_download_course_builds_outline_and_html(tmp_path):
    logs = []
    meta = download_course("https://www.udemy.com/course/test-course/", "TOK", tmp_path, ["en", "vi"],
                           client_factory=ResClient, vtt_fetcher=fake_vtt, file_fetcher=fake_file, log=logs.append)
    d = tmp_path / "test-course"
    assert meta["html"] is True
    saved = json.loads((d / "course.json").read_text(encoding="utf-8"))
    assert saved["html"] is True
    (ch,) = saved["outline"]
    assert [(l["title"], l["kind"]) for l in ch["lectures"]] == [("A1", "video"), ("Reading", "article")]
    a1, reading = ch["lectures"]
    assert a1["number"] == "01.01" and a1["captions"] == {"en": "manual", "vi": None}
    assert a1["transcripts"] == {"en": True, "vi": False}
    assert [r["kind"] for r in a1["resources"]] == ["file", "link"]
    assert reading["resources"][0] == {"kind": "file", "name": "guide (3).pdf", "path": "resources/01 Intro/guide (3).pdf", "ok": True}
    assert reading["resources"][1]["ok"] is False  # broken.docx không lấy được link

    index = (d / "index.html").read_text(encoding="utf-8")
    assert 'href="resources/01 Intro/guide (3).pdf"' in index and "broken.docx — chưa tải được" in index
    assert (d / "transcript.en.html").exists() and not (d / "transcript.vi.html").exists()
    assert any("Đã dựng trang đọc trên trình duyệt" in line for line in logs)


def test_download_course_html_failure_is_non_fatal(tmp_path, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("template hỏng")
    monkeypatch.setattr(render, "render_course", boom)
    logs = []
    meta = download_course("https://www.udemy.com/course/test-course/", "TOK", tmp_path, ["en"],
                           client_factory=FakeClient, vtt_fetcher=fake_vtt, log=logs.append)
    assert meta["html"] is False and meta["stats"]["en"]["downloaded"] == 2
    assert any("CẢNH BÁO: không dựng được HTML: template hỏng" in line for line in logs)


def test_outline_loose_lectures_become_chapter_zero(tmp_path):
    class Loose(FakeClient):
        def curriculum(self, course_id):
            return [lecture_item(1, "Pre", 100, captions=[cap("en_US")]), chapter_item(2, "C1", 90),
                    lecture_item(3, "In", 80, captions=[cap("en_US")])]
    meta = download_course("https://www.udemy.com/course/x/", "TOK", tmp_path, ["en"],
                           client_factory=Loose, vtt_fetcher=fake_vtt, log=lambda m: None)
    assert [(c["index"], [l["number"] for l in c["lectures"]]) for c in meta["outline"]] == [(0, ["00.01"]), (1, ["01.01"])]
    assert "<h2>Mở đầu</h2>" in (tmp_path / "x" / "index.html").read_text(encoding="utf-8")


# ── /view ───────────────────────────────────────────────────

@pytest.fixture
def api(data_dir):
    return TestClient(main.app)


@pytest.fixture
def served(data_dir, course):
    d = config.COURSES_DIR / "c"
    config.COURSES_DIR.mkdir(parents=True, exist_ok=True)
    course.rename(d)
    (d / "course.json").write_text(json.dumps(make_meta()), encoding="utf-8")
    render.render_course(d)
    (d / "resources" / "01 Intro").mkdir(parents=True)
    (d / "resources" / "01 Intro" / "a b.pdf").write_bytes(b"%PDF-1.4")
    (config.DATA_DIR / "token.txt").write_text("SECRET", encoding="utf-8")
    return d


def test_view_redirects_to_trailing_slash(api, served):
    r = api.get("/view/c", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/view/c/"


def test_view_serves_pages_with_csp(api, served):
    r = api.get("/view/c/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "connect-src 'none'" in r.headers["content-security-policy"]
    r = api.get("/view/c/transcript.en.html")
    assert r.status_code == 200 and '<article id="l-01-01">' in r.text


def test_view_serves_resources_without_csp(api, served):
    r = api.get("/view/c/resources/01%20Intro/a%20b.pdf")
    assert r.status_code == 200 and r.content == b"%PDF-1.4"
    assert "content-security-policy" not in r.headers


@pytest.mark.parametrize("path", ["../token.txt", "..%2Ftoken.txt", "%2e%2e/token.txt", "missing.html", "en"])
def test_view_blocks_traversal_and_missing(api, served, path):
    r = api.get(f"/view/c/{path}")
    assert r.status_code == 404 and "SECRET" not in r.text


def test_view_unknown_course(api, served):
    assert api.get("/view/nope/").status_code == 404
    assert api.get("/view/nope", follow_redirects=False).status_code == 404


def test_html_links_are_relative_and_resolve(api, served):
    """Mọi href nội bộ trong các trang phải trỏ tới file có thật (mở từ đĩa/zip cũng chạy)."""
    for page in ("index.html", "transcript.en.html", "transcript.vi.html"):
        doc = (served / page).read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"#]+)(?:#[^"]*)?"', doc):
            href = href.replace("&amp;", "&")
            if href.startswith("http"):
                continue
            assert not href.startswith("/"), href
            if "gone.docx" not in href:
                assert (served / href).exists(), f"{page}: {href}"
