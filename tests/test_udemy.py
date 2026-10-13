import json

import pytest

import udemy
from udemy import (
    AuthError, Cue, NotFoundError, UdemyError, build_structure, cues_to_srt, cues_to_text,
    download_course, is_auto_caption, parse_course_url, parse_token, parse_vtt, pick_caption,
    sanitize_filename,
)


# ── parse_course_url ────────────────────────────────────────

@pytest.mark.parametrize("url, expected", [
    ("https://www.udemy.com/course/python-bootcamp/", ("www.udemy.com", "python-bootcamp")),
    ("https://www.udemy.com/course/python-bootcamp", ("www.udemy.com", "python-bootcamp")),
    ("www.udemy.com/course/python-bootcamp/learn/lecture/123#overview", ("www.udemy.com", "python-bootcamp")),
    ("https://udemy.com/course/abc/?couponCode=X", ("www.udemy.com", "abc")),
    ("https://acme.udemy.com/course/abc/", ("acme.udemy.com", "abc")),
    ("  https://WWW.UDEMY.COM/course/abc/  ", ("www.udemy.com", "abc")),
])
def test_parse_course_url_ok(url, expected):
    assert parse_course_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://evil.com/course/abc/",
    "https://udemy.com.evil.com/course/abc/",
    "https://evil-udemy.com/course/abc/",
    "https://www.udemy.com/home/my-courses/",
    "",
])
def test_parse_course_url_rejects(url):
    with pytest.raises(ValueError):
        parse_course_url(url)


# ── parse_token ─────────────────────────────────────────────

def test_parse_token_bare():
    assert parse_token("  abc123  ") == ("abc123", {"access_token": "abc123"})


def test_parse_token_cookie_header():
    tok, cookies = parse_token("Cookie: __udmy_2_v57r=x; access_token=TOK; cf_clearance=CF")
    assert tok == "TOK"
    assert cookies == {"__udmy_2_v57r": "x", "access_token": "TOK", "cf_clearance": "CF"}


def test_parse_token_single_pair():
    assert parse_token("access_token=TOK")[0] == "TOK"


def test_parse_token_cookie_without_access_token():
    assert parse_token("a=1; b=2")[0] == ""


def test_parse_token_empty():
    assert parse_token("") == ("", {})


# ── sanitize_filename ───────────────────────────────────────

def test_sanitize_filename():
    assert sanitize_filename('01.02 What is "AI"? / ML: intro*') == "01.02 What is -AI-- - ML- intro-"
    assert sanitize_filename("trailing dots...  ") == "trailing dots"
    assert sanitize_filename("  ") == "untitled"
    assert len(sanitize_filename("x" * 500)) == 120


# ── VTT ─────────────────────────────────────────────────────

VTT = """﻿WEBVTT
Kind: captions

NOTE this is a comment

1
00:00:01.000 --> 00:00:03.500 align:start position:0%
Hello <c.colorE5E5E5>world</c>

2
00:01:02.25 --> 01:00:03.000
Second &amp; line
two

00:00:05.000 --> 00:00:06.000

bad --> timestamps
text
"""


def test_parse_vtt():
    cues = parse_vtt(VTT.replace("\n", "\r\n"))
    assert [c.text for c in cues] == ["Hello world", "Second & line\ntwo"]
    assert cues[0].start == 1.0 and cues[0].end == 3.5
    assert cues[1].start == pytest.approx(62.25) and cues[1].end == 3603.0


def test_parse_vtt_header_without_blank_line():
    cues = parse_vtt("WEBVTT\n00:00.000 --> 00:01.000\nHi")
    assert len(cues) == 1 and cues[0].text == "Hi"


def test_cues_to_srt():
    srt = cues_to_srt([Cue(1.0, 3.5, "a"), Cue(3661.007, 3662.0, "b\nc")])
    assert srt == "1\n00:00:01,000 --> 00:00:03,500\na\n\n2\n01:01:01,007 --> 01:01:02,000\nb\nc\n"


def test_cues_to_text_joins_dedupes_and_breaks_on_pause():
    cues = [
        Cue(0, 1, "Hello"), Cue(1, 2, "there."), Cue(2, 3, "there."),  # cue lặp
        Cue(6, 7, "New  paragraph"), Cue(7, 8, "here."),
    ]
    assert cues_to_text(cues) == "Hello there.\n\nNew paragraph here."


def test_cues_to_text_no_break_mid_sentence_even_with_pause():
    assert cues_to_text([Cue(0, 1, "So"), Cue(10, 11, "anyway.")]) == "So anyway."


def test_cues_to_text_breaks_long_paragraph_at_sentence_end():
    cues = [Cue(i, i + 1, f"word{i} " * 30 + "end.") for i in range(10)]
    assert cues_to_text(cues, para_chars=300).count("\n\n") >= 2


# ── Captions ────────────────────────────────────────────────

def cap(locale, source="manual", url="https://vtt-c.udemycdn.com/x.vtt", title=""):
    return {"locale_id": locale, "source": source, "url": url, "title": title}


def test_pick_caption_prefers_manual():
    caps = [cap("en_US", "auto"), cap("en_GB", "manual", url="manual")]
    assert pick_caption(caps, "en")["url"] == "manual"


def test_pick_caption_lang_matching():
    caps = [cap("vi_VN"), cap("en-US", url="en")]
    assert pick_caption(caps, "EN")["url"] == "en"
    assert pick_caption(caps, "ja") is None
    assert pick_caption([cap("vi_VN", url=None)], "vi") is None


def test_is_auto_caption_variants():
    assert is_auto_caption({"source": "auto"})
    assert is_auto_caption({"title": "Tiếng Việt [Auto]"})
    assert is_auto_caption({"video_label": "English [Auto]"})
    assert not is_auto_caption({"source": "manual", "title": "English"})


# ── Curriculum ──────────────────────────────────────────────

def lecture_item(id_, title, sort_order, asset_type="Video", captions=None):
    return {"_class": "lecture", "id": id_, "title": title, "sort_order": sort_order,
            "asset": {"asset_type": asset_type, "time_estimation": 125, "captions": captions or []}}


def chapter_item(id_, title, sort_order):
    return {"_class": "chapter", "id": id_, "title": title, "sort_order": sort_order}


CURRICULUM = [  # cố ý xáo trộn — thứ tự đúng do sort_order giảm dần quyết định
    lecture_item(12, "B2", 10, captions=[cap("en_US")]),
    chapter_item(1, "Intro", 100),
    lecture_item(10, "Loose", 110),
    lecture_item(11, "A1", 90, captions=[cap("en_US"), cap("vi_VN", "auto")]),
    {"_class": "quiz", "id": 99, "title": "Quiz", "sort_order": 80},
    lecture_item(13, "Article", 70, asset_type="Article"),
    chapter_item(2, "Deep dive", 50),
    lecture_item(14, "B1", 40, captions=[cap("en_US", url=None)]),
]


def test_build_structure():
    chapters = build_structure(CURRICULUM)
    assert [(c.index, c.title) for c in chapters] == [(0, ""), (1, "Intro"), (2, "Deep dive")]
    assert [(l.number, l.title) for c in chapters for l in c.lectures] == [
        ("00.01", "Loose"), ("01.01", "A1"), ("02.01", "B1"), ("02.02", "B2"),
    ]
    b1 = chapters[2].lectures[0]
    assert b1.captions == []  # caption không có url bị lọc
    assert b1.duration == 125 and b1.stem == "02.01 B1"


def test_build_structure_keeps_api_order_without_sort_order():
    items = [chapter_item(1, "C", None), lecture_item(2, "L1", None), lecture_item(3, "L2", None)]
    for it in items:
        del it["sort_order"]
    chapters = build_structure(items)
    assert [l.title for l in chapters[0].lectures] == ["L1", "L2"]


# ── UdemyClient (HTTP giả) ──────────────────────────────────

class FakeResp:
    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def get(self, url, params=None):
        self.calls.append((url, params))
        for key, resp in self.routes:
            if key in url:
                return resp(url, params) if callable(resp) else resp
        return FakeResp(404, text="nf")


def make_client(routes):
    client = udemy.UdemyClient.__new__(udemy.UdemyClient)
    client.host, client.base = "www.udemy.com", "https://www.udemy.com"
    client.session = FakeSession(routes)
    return client


def test_client_requires_token():
    with pytest.raises(AuthError):
        udemy.UdemyClient("www.udemy.com", "a=1; b=2")


def test_get_refuses_foreign_host():
    client = make_client([])
    with pytest.raises(UdemyError, match="host lạ"):
        client.get_json("https://evil.com/api")


@pytest.mark.parametrize("status, text, exc, match", [
    (401, "", AuthError, "401"),
    (403, "<title>Just a moment...</title>", UdemyError, "Cloudflare"),
    (403, "forbidden", AuthError, "403"),
    (404, "", NotFoundError, "404"),
    (418, "", UdemyError, "418"),
])
def test_get_error_mapping(status, text, exc, match):
    client = make_client([("/api", FakeResp(status, text=text))])
    with pytest.raises(exc, match=match):
        client.get_json("/api")


def test_get_json_html_response():
    client = make_client([("/api", FakeResp(200, text="<!DOCTYPE html>"))])
    with pytest.raises(UdemyError, match="HTML"):
        client.get_json("/api")


def test_get_retries_on_429(monkeypatch):
    monkeypatch.setattr(udemy.time, "sleep", lambda s: None)
    seq = iter([FakeResp(429, text=""), FakeResp(200, {"ok": 1})])
    client = make_client([("/api", lambda u, p: next(seq))])
    assert client.get_json("/api") == {"ok": 1}


def test_curriculum_follows_pagination():
    pages = {
        "page=2": FakeResp(200, {"results": [{"id": 2}], "next": None}),
        "items": FakeResp(200, {"results": [{"id": 1}], "next": "https://www.udemy.com/api-2.0/courses/5/subscriber-curriculum-items/?page=2"}),
    }
    client = make_client([("page=2", pages["page=2"]), ("items", pages["items"])])
    assert client.curriculum(5) == [{"id": 1}, {"id": 2}]
    assert client.session.calls[1][1] is None  # trang sau không gửi lại params


def test_curriculum_refuses_next_on_foreign_host():
    client = make_client([("items", FakeResp(200, {"results": [], "next": "https://evil.com/x"}))])
    with pytest.raises(UdemyError, match="host lạ"):
        client.curriculum(5)


def test_resolve_course_via_subscribed_search():
    client = make_client([("subscribed-courses", FakeResp(200, {"results": [
        {"id": 1, "published_title": "other"}, {"id": 7, "title": "My Course", "published_title": "my-course"},
    ]}))])
    assert client.resolve_course("my-course") == {"id": 7, "title": "My Course", "published_title": "my-course"}


def test_resolve_course_falls_back_to_subscription_then_html():
    def route(url, params):
        if "subscription-course-enrollments" in url:
            return FakeResp(403, text="no plan")
        if "subscribed-courses" in url:
            return FakeResp(200, {"results": [], "next": None})
        if "/course/my-course/" in url:
            return FakeResp(200, text='<body data-clp-course-id="4242">')
        if "/api-2.0/courses/4242/" in url:
            return FakeResp(200, {"title": "Scraped"})
        return FakeResp(404, text="")
    client = make_client([("", route)])
    assert client.resolve_course("my-course") == {"id": 4242, "title": "Scraped", "published_title": "my-course"}


def test_resolve_course_propagates_401():
    client = make_client([("", FakeResp(401, text=""))])
    with pytest.raises(AuthError, match="401"):
        client.resolve_course("x")


def test_resolve_course_not_found():
    def route(url, params):
        if "/api-2.0/users/me/" in url:
            return FakeResp(200, {"results": []})
        return FakeResp(200, text="<html>no id</html>")
    with pytest.raises(NotFoundError):
        make_client([("", route)]).resolve_course("x")


# ── download_course end-to-end ──────────────────────────────

class FakeClient:
    def __init__(self, host, token):
        assert token == "TOK"

    def me(self):
        return {"id": 1}

    def course_details(self, course_id):
        return {"title": "Test Course", "headline": "Learn things", "description": "<p>Desc</p>"}

    def resolve_course(self, slug):
        return {"id": 5, "title": "Test Course", "published_title": slug}

    def curriculum(self, course_id):
        return CURRICULUM


def fake_vtt(url):
    if "boom" in url:
        raise UdemyError("cdn down")
    return f"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nfrom {url}.\n"


def run(tmp_path, **kw):
    logs = []
    meta = download_course("https://www.udemy.com/course/test-course/", "TOK", tmp_path, kw.pop("langs", ["en", "vi"]),
                           client_factory=kw.pop("client_factory", FakeClient), vtt_fetcher=kw.pop("vtt_fetcher", fake_vtt),
                           log=logs.append, **kw)
    return meta, logs


def test_download_course_writes_files(tmp_path):
    meta, _ = run(tmp_path)
    d = tmp_path / "test-course"
    assert (d / "en" / "01.01 A1.srt").read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> 00:00:01,000\nfrom ")
    assert (d / "en" / "02.02 B2.txt").exists()
    assert (d / "vi" / "01.01 A1.txt").exists()
    assert not (d / "en" / "00.01 Loose.txt").exists()  # bài không có phụ đề

    assert meta["stats"]["en"] == {"available": 2, "downloaded": 2, "skipped": 0, "missing": 2, "failed": 0, "auto": 0}
    assert meta["stats"]["vi"]["auto"] == 1 and meta["combined"] == {"en": 2, "vi": 1}
    assert meta["slug"] == "test-course" and meta["lecture_count"] == 4

    combined = (d / "transcript.en.md").read_text(encoding="utf-8")
    assert combined.index("## 1. Intro") < combined.index("### 01.01 A1") < combined.index("## 2. Deep dive") < combined.index("### 02.02 B2")
    assert "Loose" not in combined
    contents = (d / "CONTENTS.md").read_text(encoding="utf-8")
    assert "- 01.01 A1 [2:05] — en, vi (auto)" in contents
    assert "- 00.01 Loose [2:05] — ~~en~~, ~~vi~~" in contents
    assert json.loads((d / "course.json").read_text(encoding="utf-8"))["id"] == 5


def test_download_course_resumes_and_force(tmp_path):
    run(tmp_path)
    calls = []
    meta, _ = run(tmp_path, vtt_fetcher=lambda u: calls.append(u) or fake_vtt(u))
    assert calls == [] and meta["stats"]["en"]["skipped"] == 2
    assert meta["combined"]["en"] == 2  # file gộp vẫn đủ dù không tải lại
    meta, _ = run(tmp_path, force=True, vtt_fetcher=lambda u: calls.append(u) or fake_vtt(u))
    assert len(calls) == 3 and meta["stats"]["en"]["downloaded"] == 2


def test_download_course_single_failure_does_not_abort(tmp_path):
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) == 1:
            raise UdemyError("cdn down")
        return fake_vtt(url)
    meta, logs = run(tmp_path, langs=["en"], vtt_fetcher=flaky)
    assert meta["stats"]["en"]["failed"] == 1 and meta["stats"]["en"]["downloaded"] == 1
    assert any("LỖI" in line for line in logs)


def test_download_course_removes_stale_combined_when_lang_empty(tmp_path):
    d = tmp_path / "test-course"
    d.mkdir()
    (d / "transcript.ja.md").write_text("old", encoding="utf-8")
    meta, _ = run(tmp_path, langs=["ja"])
    assert meta["combined"] == {"ja": 0} and not (d / "transcript.ja.md").exists()


def test_download_course_rejects_bad_url(tmp_path):
    with pytest.raises(ValueError):
        download_course("https://evil.com/course/x/", "TOK", tmp_path, ["en"], client_factory=FakeClient)


def test_download_course_invalid_token_fails_fast(tmp_path):
    class Rejected(FakeClient):
        def me(self):
            raise AuthError("Không có quyền truy cập (403)", 403)

        def resolve_course(self, slug):
            raise AssertionError("không được dò khoá khi token sai")
    with pytest.raises(AuthError, match="Token không hợp lệ"):
        download_course("https://www.udemy.com/course/x/", "TOK", tmp_path, ["en"], client_factory=Rejected)


def test_resolve_course_direct_slug_lookup_first():
    client = make_client([("/api-2.0/courses/my-course/", FakeResp(200, {"id": 9, "title": "Direct"}))])
    assert client.resolve_course("my-course") == {"id": 9, "title": "Direct", "published_title": "my-course"}
    assert len(client.session.calls) == 1


def test_resolve_course_skips_5xx_source_and_never_uses_search(monkeypatch):
    """Hồi quy: Udemy Business trả 500 cho subscribed-courses?search= → không được làm hỏng job."""
    monkeypatch.setattr(udemy.time, "sleep", lambda s: None)

    def route(url, params):
        if "/api-2.0/courses/" in url:
            return FakeResp(404, text="")
        if "subscribed-courses" in url:
            assert "search" not in (params or {})
            return FakeResp(500, text='{"detail":"Internal server error."}')
        if "subscription-course-enrollments" in url:
            return FakeResp(200, {"results": [{"id": 3, "title": "Plan", "url": "/course/my-course/"}], "next": None})
        return FakeResp(404, text="")
    assert make_client([("", route)]).resolve_course("my-course")["id"] == 3
