"""Tải tài nguyên đính kèm (supplementary assets: pdf, docx, link ngoài)."""
import sys
import types

import pytest

from test_udemy import FakeClient, FakeResp, cap, chapter_item, fake_vtt, lecture_item, make_client, run
from udemy import Resource, UdemyError, collect_resources, download_course, fetch_file


def res_asset(id_, title, filename, asset_type="File", external_url=None):
    return {"id": id_, "asset_type": asset_type, "title": title, "filename": filename, "external_url": external_url}


@pytest.mark.parametrize("asset, expected", [
    (res_asset(1, "Work_book v2.docx", "Work-book-v2.docx"), "Work_book v2.docx"),  # title = tên gốc
    (res_asset(1, "Workbook", "workbook.pdf"), "workbook.pdf"),                      # title không có đuôi
    (res_asset(1, "a/b:c?.pdf", "x.pdf"), "a-b-c-.pdf"),
    (res_asset(1, "", ""), "asset-1"),
    (res_asset(1, "x" * 300 + ".pdf", "y.pdf"), "x" * 96 + ".pdf"),               # cắt còn 100 ký tự, giữ đuôi
])
def test_resource_filename(asset, expected):
    assert Resource(1, "L", 1, "C", asset).filename == expected


def test_collect_resources_includes_article_lectures_and_numbers_chapters():
    items = [
        lecture_item(10, "Loose", 110),
        chapter_item(1, "Intro", 100),
        {**lecture_item(11, "Video", 90), "supplementary_assets": [res_asset(5, "a.pdf", "a.pdf")]},
        {**lecture_item(12, "Article", 80, asset_type="Article"),
         "supplementary_assets": [res_asset(6, "b.docx", "b.docx"), {"title": "no id"}]},
        chapter_item(2, "Next: part/2", 50),
        {**lecture_item(13, "V2", 40), "supplementary_assets": [res_asset(7, "Site", "", "ExternalLink", "https://x.y")]},
    ]
    res = collect_resources(items)
    assert [(r.asset["id"], r.lecture_title, r.folder) for r in res] == [
        (5, "Video", "01 Intro"), (6, "Article", "01 Intro"), (7, "V2", "02 Next- part-2"),
    ]
    assert [r.is_link for r in res] == [False, False, True]


def test_asset_download_url():
    data = {"download_urls": {"File": [{"label": "download", "file": "https://att-c.udemycdn.com/f.docx"}]}}
    client = make_client([("/supplementary-assets/27/", FakeResp(200, data))])
    assert client.asset_download_url(5, 11, 27) == "https://att-c.udemycdn.com/f.docx"
    url, params = client.session.calls[0]
    assert "/users/me/subscribed-courses/5/lectures/11/supplementary-assets/27/" in url
    assert params == {"fields[asset]": "download_urls"}


def test_asset_download_url_missing():
    client = make_client([("/supplementary-assets/", FakeResp(200, {"download_urls": None}))])
    with pytest.raises(UdemyError, match="link tải"):
        client.asset_download_url(5, 11, 27)


def test_curriculum_requests_supplementary_assets():
    client = make_client([("items", FakeResp(200, {"results": [], "next": None}))])
    client.curriculum(5)
    params = client.session.calls[0][1]
    assert "supplementary_assets" in params["fields[lecture]"]
    assert {"captions", "filename", "title", "external_url"} <= set(params["fields[asset]"].split(","))


# ── download_course với tài nguyên ──────────────────────────

RES_CURRICULUM = [
    chapter_item(1, "Intro", 100),
    {**lecture_item(11, "A1", 90, captions=[cap("en_US")]), "supplementary_assets": [
        res_asset(1, "guide.pdf", "guide.pdf"), res_asset(2, "Docs", "", "ExternalLink", "https://docs.example")]},
    {**lecture_item(12, "Reading", 80, asset_type="Article"), "supplementary_assets": [
        res_asset(3, "guide.pdf", "guide.pdf"),  # trùng tên trong cùng chương
        res_asset(4, "broken.docx", "broken.docx")]},
]


class ResClient(FakeClient):
    def curriculum(self, course_id):
        return RES_CURRICULUM

    def asset_download_url(self, course_id, lecture_id, asset_id):
        if asset_id == 4:
            raise UdemyError("Udemy không trả link tải cho file này")
        return f"https://att-c.udemycdn.com/{asset_id}"


def fake_file(url, dest):
    dest.write_bytes(f"bytes of {url}".encode())


def run_res(tmp_path, **kw):
    logs = []
    meta = download_course("https://www.udemy.com/course/test-course/", "TOK", tmp_path, ["en"],
                           client_factory=kw.pop("client_factory", ResClient), vtt_fetcher=fake_vtt,
                           file_fetcher=kw.pop("file_fetcher", fake_file), log=logs.append, **kw)
    return meta, logs


def test_download_course_resources(tmp_path):
    meta, logs = run_res(tmp_path)
    d = tmp_path / "test-course" / "resources"
    assert (d / "01 Intro" / "guide.pdf").read_bytes() == b"bytes of https://att-c.udemycdn.com/1"
    assert (d / "01 Intro" / "guide (3).pdf").read_bytes() == b"bytes of https://att-c.udemycdn.com/3"
    assert not (d / "01 Intro" / "broken.docx").exists()
    assert meta["resources"] == {"files": 3, "downloaded": 2, "skipped": 0, "failed": 1, "links": 1}
    assert meta["stats"]["en"]["downloaded"] == 1  # transcript vẫn tải bình thường
    assert any(line == "[file] LỖI broken.docx: Udemy không trả link tải cho file này" for line in logs)

    index = (d / "INDEX.md").read_text(encoding="utf-8")
    assert index.index("## 1. Intro") < index.index("- **A1**") < index.index("- **Reading**")
    assert "  - [guide.pdf](<01 Intro/guide.pdf>)" in index
    assert "  - [guide (3).pdf](<01 Intro/guide (3).pdf>)" in index
    assert "  - \U0001f517 [Docs](https://docs.example)" in index
    assert "  - [broken.docx](<01 Intro/broken.docx>) — *chưa tải được*" in index


def test_download_course_resources_resume_and_force(tmp_path):
    run_res(tmp_path)
    calls = []
    meta, _ = run_res(tmp_path, file_fetcher=lambda u, p: calls.append(u) or fake_file(u, p))
    assert calls == [] and meta["resources"]["skipped"] == 2 and meta["resources"]["failed"] == 1
    meta, _ = run_res(tmp_path, force=True, file_fetcher=lambda u, p: calls.append(u) or fake_file(u, p))
    assert len(calls) == 2 and meta["resources"]["downloaded"] == 2


def test_download_course_resource_fetch_failure_isolated(tmp_path):
    def fail(url, dest):
        raise UdemyError("Tải file lỗi HTTP 403")
    meta, logs = run_res(tmp_path, file_fetcher=fail)
    assert meta["resources"]["failed"] == 3 and meta["stats"]["en"]["downloaded"] == 1
    assert any("LỖI [file] guide.pdf: Tải file lỗi HTTP 403" in line for line in logs)


def test_download_course_resources_disabled(tmp_path):
    class NoAssetCalls(ResClient):
        def asset_download_url(self, *a):
            raise AssertionError("không được gọi khi resources=False")
    meta, _ = run_res(tmp_path, resources=False, client_factory=NoAssetCalls)
    assert meta["resources"] is None
    assert not (tmp_path / "test-course" / "resources").exists()


def test_download_course_no_resources_no_index(tmp_path):
    meta, _ = run(tmp_path, langs=["en"])
    assert meta["resources"] == {"files": 0, "downloaded": 0, "skipped": 0, "failed": 0, "links": 0}
    assert not (tmp_path / "test-course" / "resources").exists()


# ── fetch_file ──────────────────────────────────────────────

class FakeStreamResp:
    def __init__(self, status, chunks, fail_at=None):
        self.status_code, self.chunks, self.fail_at, self.closed = status, chunks, fail_at, False

    def iter_content(self):
        for i, c in enumerate(self.chunks):
            if i == self.fail_at:
                raise ConnectionError("mất mạng")
            yield c

    def close(self):
        self.closed = True


@pytest.fixture
def fake_curl(monkeypatch):
    state = {}
    mod = types.ModuleType("curl_cffi")
    mod.requests = types.SimpleNamespace(get=lambda url, **kw: state["resp"])
    monkeypatch.setitem(sys.modules, "curl_cffi", mod)
    return state


def test_fetch_file_ok(tmp_path, fake_curl):
    fake_curl["resp"] = FakeStreamResp(200, [b"ab", b"cd"])
    fetch_file("https://att-c.udemycdn.com/x", tmp_path / "x.pdf")
    assert (tmp_path / "x.pdf").read_bytes() == b"abcd"
    assert not (tmp_path / "x.pdf.part").exists() and fake_curl["resp"].closed


def test_fetch_file_partial_download_leaves_nothing(tmp_path, fake_curl):
    fake_curl["resp"] = FakeStreamResp(200, [b"ab", b"cd"], fail_at=1)
    with pytest.raises(ConnectionError):
        fetch_file("https://att-c.udemycdn.com/x", tmp_path / "x.pdf")
    assert list(tmp_path.iterdir()) == []  # không để lại file dở → lần sau tải lại


def test_fetch_file_http_error(tmp_path, fake_curl):
    fake_curl["resp"] = FakeStreamResp(403, [])
    with pytest.raises(UdemyError, match="403"):
        fetch_file("https://att-c.udemycdn.com/x", tmp_path / "x.pdf")
    assert list(tmp_path.iterdir()) == []
