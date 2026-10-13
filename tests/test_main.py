import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

import config
import main
from udemy import AuthError


@pytest.fixture
def client(data_dir, monkeypatch):
    with main.jobs_lock:
        main.jobs.clear()
    return TestClient(main.app)


def make_course(slug="my-course", langs=("en",)):
    d = config.COURSES_DIR / slug
    d.mkdir(parents=True)
    meta = {"slug": slug, "title": "T", "url": f"https://www.udemy.com/course/{slug}/", "langs": list(langs),
            "stats": {}, "combined": {l: 1 for l in langs}, "lecture_count": 1, "chapter_count": 1, "updated_at": 1}
    (d / "course.json").write_text(json.dumps(meta), encoding="utf-8")
    for l in langs:
        (d / f"transcript.{l}.md").write_text(f"# T [{l}]", encoding="utf-8")
        (d / l).mkdir()
        (d / l / "01.01 A.srt").write_text("1\n", encoding="utf-8")
    return d


# ── token ───────────────────────────────────────────────────

def test_token_none(client):
    assert client.get("/api/token").json() == {"source": "none", "configured": False}


def test_token_env_then_web_overrides_then_clear(client, monkeypatch):
    monkeypatch.setenv("UDEMY_ACCESS_TOKEN", "ENVTOK")
    assert client.get("/api/token").json()["source"] == "env"

    class FakeUdemy:
        def __init__(self, host, token):
            assert token == "WEBTOK"
        def me(self):
            return {"display_name": "Manh"}
    monkeypatch.setattr(main, "UdemyClient", FakeUdemy)
    r = client.post("/api/token", json={"token": "  WEBTOK  "})
    assert r.json() == {"source": "web", "configured": True, "valid": True, "user": "Manh"}
    assert config.TOKEN_FILE.read_text(encoding="utf-8") == "WEBTOK"

    assert client.delete("/api/token").json()["source"] == "env"
    assert not config.TOKEN_FILE.exists()


def test_token_never_echoed(client, monkeypatch):
    class Bad:
        def __init__(self, host, token):
            pass
        def me(self):
            raise AuthError("Token không hợp lệ (401)", 401)
    monkeypatch.setattr(main, "UdemyClient", Bad)
    r = client.post("/api/token", json={"token": "SECRET-TOKEN-123"})
    assert r.json()["valid"] is False
    assert "SECRET-TOKEN-123" not in r.text
    assert "SECRET-TOKEN-123" not in client.get("/api/token?check=1").text


def test_token_empty_rejected(client):
    assert client.post("/api/token", json={"token": "   "}).status_code == 400


# ── jobs ────────────────────────────────────────────────────

@pytest.mark.parametrize("payload", [
    {"url": "https://evil.com/course/x/"},
    {"url": "https://www.udemy.com/home/"},
    {"url": "https://www.udemy.com/course/x/", "langs": ["../etc"]},
    {"url": "https://www.udemy.com/course/x/", "langs": [" "]},
])
def test_create_job_validation(client, payload):
    assert client.post("/api/jobs", json=payload).status_code == 400


def wait_job(client, job_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError("job không xong")


def test_job_runs_and_reports(client, monkeypatch):
    seen = {}

    def fake_download(url, token, out_root, langs, force, resources, workers, log, progress):
        seen.update(url=url, langs=langs, force=force, resources=resources, out_root=out_root)
        log("hello")
        progress(3, 3)
        return {"slug": "x", "stats": {"en": {"downloaded": 3}}}
    monkeypatch.setattr(main, "download_course", fake_download)

    job = client.post("/api/jobs", json={"url": "https://www.udemy.com/course/x/", "langs": ["EN", "vi"], "force": True, "resources": False}).json()
    assert job["status"] == "queued" and job["slug"] == "x"
    job = wait_job(client, job["id"])
    assert job["status"] == "done" and job["done"] == 3 and job["total"] == 3
    assert any(line.endswith("hello") for line in job["logs"])
    assert seen == {"url": "https://www.udemy.com/course/x/", "langs": ["en", "vi"], "force": True, "resources": False, "out_root": config.COURSES_DIR}
    assert "logs" not in client.get("/api/jobs").json()[0]


def test_job_default_langs_and_error(client, monkeypatch):
    def boom(url, token, out_root, langs, **kw):
        assert langs == config.DEFAULT_LANGS and kw["resources"] is True
        raise AuthError("Token hết hạn", 401)
    monkeypatch.setattr(main, "download_course", boom)
    job = wait_job(client, client.post("/api/jobs", json={"url": "https://www.udemy.com/course/x/"}).json()["id"])
    assert job["status"] == "error" and "Token hết hạn" in job["error"]


def test_get_unknown_job(client):
    assert client.get("/api/jobs/nope").status_code == 404


# ── courses ─────────────────────────────────────────────────

def test_list_courses_skips_broken(client):
    assert client.get("/api/courses").json() == []
    make_course("a")
    broken = config.COURSES_DIR / "b"
    broken.mkdir()
    (broken / "course.json").write_text("{not json", encoding="utf-8")
    assert [c["slug"] for c in client.get("/api/courses").json()] == ["a"]


def test_transcript_view_and_download(client):
    make_course("a", langs=("en", "vi"))
    r = client.get("/api/courses/a/transcript/vi")
    assert r.status_code == 200 and r.text == "# T [vi]"
    r = client.get("/api/courses/a/transcript/en?download=1")
    assert "attachment" in r.headers["content-disposition"] and "a.en.md" in r.headers["content-disposition"]
    assert client.get("/api/courses/a/transcript/ja").status_code == 404
    assert client.get("/api/courses/a/transcript/EN!").status_code == 400


@pytest.mark.parametrize("slug", ["..", "missing", "%2e%2e", "..%2Fcourses"])
def test_course_path_traversal_rejected(client, slug):
    make_course("a")
    (config.DATA_DIR / "course.json").write_text("{}", encoding="utf-8")  # mồi: thư mục cha có course.json
    assert client.get(f"/api/courses/{slug}/zip").status_code == 404
    assert client.get(f"/api/courses/{slug}/transcript/en").status_code in (400, 404)


def test_zip(client):
    make_course("a")
    r = client.get("/api/courses/a/zip")
    assert r.status_code == 200
    names = set(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
    assert {"a/course.json", "a/transcript.en.md", "a/en/01.01 A.srt"} <= names


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Udemy Transcript" in r.text
