"""Tổng quan khoá (headline, mô tả, bạn sẽ học được gì...) → OVERVIEW.md."""
import json

import pytest
from fastapi.testclient import TestClient

import config
import main
from test_udemy import FakeClient, FakeResp, make_client, run
from udemy import COURSE_DETAIL_FIELDS, UdemyError, html_to_markdown


# ── html_to_markdown ────────────────────────────────────────

def test_html_paragraphs_and_inline():
    src = "<p>Hello <strong>bold</strong> and <em>it</em>.</p>\n  <p>Second&nbsp;para &amp; more</p>"
    assert html_to_markdown(src) == "Hello **bold** and *it*.\n\nSecond para & more"  # &nbsp; → dấu cách thường


def test_html_lists_nested_and_ordered():
    src = "<p>Intro</p><ul><li>One</li><li>Two<ul><li>Sub</li></ul></li></ul><ol><li>A</li><li>B</li></ol>"
    assert html_to_markdown(src) == "Intro\n\n- One\n- Two\n  - Sub\n\n1. A\n2. B"


def test_html_headings_demoted_links_and_br():
    src = '<h2>Why</h2><p>See <a href="https://x.y">site</a><br>next line</p><p><strong></strong></p>'
    assert html_to_markdown(src) == "#### Why\n\nSee [site](https://x.y)\nnext line"


def test_html_empty():
    assert html_to_markdown("") == "" and html_to_markdown(None) == ""


# ── client ──────────────────────────────────────────────────

def test_course_details_requests_overview_fields():
    client = make_client([("/api-2.0/courses/5/", FakeResp(200, {"title": "T"}))])
    assert client.course_details(5) == {"title": "T"}
    params = client.session.calls[0][1]
    assert params == {"fields[course]": COURSE_DETAIL_FIELDS}
    for f in ("headline", "description", "what_you_will_learn_data", "requirements_data", "target_audiences"):
        assert f in COURSE_DETAIL_FIELDS.split(",")


# ── download_course ghi OVERVIEW.md ─────────────────────────

FULL_DETAILS = {
    "title": "Test Course",
    "headline": "Learn things fast",
    "description": "<p>Long <strong>desc</strong></p><ul><li>point</li></ul>",
    "what_you_will_learn_data": {"items": ["Skill A", " ", "Skill B"]},
    "objectives": ["ignored because what_you_will_learn_data exists"],
    "requirements_data": {"items": []},
    "prerequisites": ["Basic computer skills"],
    "target_audiences": ["New BAs"],
    "visible_instructors": [{"display_name": "Jane Doe", "job_title": "Coach"}, {"display_name": "Bob"}],
    "primary_category": {"title": "Business"}, "primary_subcategory": {"title": "Management"},
    "instructional_level_simple": "All Levels",
    "locale": {"title": "English (US)"},
    "content_info": "4.5 total hours", "num_lectures": 71,
    "rating": 4.5376, "num_reviews": 3065, "num_subscribers": 12794,
    "caption_languages": ["English [Auto]", "Vietnamese [Auto]"],
    "last_update_date": "2024-01-02",
    "url": "/course/test-course/",
}


class DetailClient(FakeClient):
    details = FULL_DETAILS

    def course_details(self, course_id):
        return self.details


def test_download_course_writes_overview(tmp_path):
    meta, logs = run(tmp_path, langs=["en"], client_factory=DetailClient)
    d = tmp_path / "test-course"
    md = (d / "OVERVIEW.md").read_text(encoding="utf-8")
    assert md.startswith("# Test Course\n\n> Learn things fast\n")
    for line in [
        "- **Giảng viên:** Jane Doe (Coach), Bob",
        "- **Danh mục:** Business › Management",
        "- **Trình độ:** All Levels",
        "- **Ngôn ngữ:** English (US)",
        "- **Thời lượng:** 4.5 total hours · 71 bài",
        "- **Đánh giá:** 4.5/5 (3,065 đánh giá) · 12,794 học viên",
        "- **Phụ đề:** English [Auto], Vietnamese [Auto]",
        "- **Cập nhật:** 2024-01-02",
        "- **Link:** https://www.udemy.com/course/test-course/",
    ]:
        assert line in md
    assert "## Bạn sẽ học được gì\n\n- Skill A\n- Skill B\n" in md and "ignored" not in md
    assert "## Yêu cầu\n\n- Basic computer skills\n" in md  # requirements_data rỗng → fallback prerequisites
    assert "## Mô tả\n\nLong **desc**\n\n- point\n" in md
    assert md.index("## Bạn sẽ học được gì") < md.index("## Yêu cầu") < md.index("## Mô tả") < md.index("## Khoá học này dành cho ai")
    assert json.loads((d / "overview.json").read_text(encoding="utf-8"))["num_lectures"] == 71
    assert meta["overview"] is True and meta["headline"] == "Learn things fast"
    assert any("OVERVIEW.md" in line for line in logs)


def test_overview_minimal_details_skips_empty_sections(tmp_path):
    class Minimal(FakeClient):
        def course_details(self, course_id):
            return {"title": "Only title", "url": "https://acme.udemy.com/course/x/"}
    run(tmp_path, langs=["en"], client_factory=Minimal)
    md = (tmp_path / "test-course" / "OVERVIEW.md").read_text(encoding="utf-8")
    assert md == "# Only title\n\n- **Link:** https://acme.udemy.com/course/x/\n"


def test_overview_failure_does_not_abort_job(tmp_path):
    class Broken(FakeClient):
        def course_details(self, course_id):
            raise UdemyError("HTTP 500", 500)
    meta, logs = run(tmp_path, langs=["en"], client_factory=Broken)
    assert meta["overview"] is False and meta["headline"] is None
    assert meta["stats"]["en"]["downloaded"] == 2  # transcript vẫn tải
    assert any("CẢNH BÁO: không lấy được tổng quan" in line for line in logs)


def test_overview_failure_keeps_previous_file(tmp_path):
    run(tmp_path, langs=["en"], client_factory=DetailClient)

    class Broken(FakeClient):
        def course_details(self, course_id):
            raise UdemyError("HTTP 500", 500)
    meta, _ = run(tmp_path, langs=["en"], client_factory=Broken)
    assert meta["overview"] is True  # bản lần trước vẫn còn, UI vẫn mở được


# ── API ─────────────────────────────────────────────────────

@pytest.fixture
def api(data_dir):
    return TestClient(main.app)


def test_overview_endpoint(api, data_dir):
    d = config.COURSES_DIR / "a"
    d.mkdir(parents=True)
    (d / "course.json").write_text("{}", encoding="utf-8")
    assert api.get("/api/courses/a/overview").status_code == 404
    (d / "OVERVIEW.md").write_text("# A", encoding="utf-8")
    assert api.get("/api/courses/a/overview").text == "# A"
    r = api.get("/api/courses/a/overview?download=1")
    assert "a.overview.md" in r.headers["content-disposition"]
    assert api.get("/api/courses/../overview").status_code == 404
