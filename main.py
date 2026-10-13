import io
import json
import os
import queue
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

import config
import i18n
from i18n import t
from udemy import UdemyClient, UdemyError, download_course, parse_course_url

app = FastAPI(title="Udemy Transcript")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
APP_HEADER = "udemy-transcript"
STATIC_DIR = Path(__file__).parent / "static"
LANG_RE = re.compile(r"^[a-z]{2,3}$")
# Trang /view chỉ là tài liệu tĩnh: chặn mọi fetch/XHR (connect-src 'none') để kể cả khi nội dung
# Udemy lọt được script vào thì cũng không gọi được /api/* (vd /api/token) của app.
VIEW_CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data: https:; "
            "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")
MAX_LOG_LINES = 500

# ── Job queue: chạy tuần tự từng khoá, 1 worker thread ──────

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
job_queue: "queue.Queue[str]" = queue.Queue()


def _update(job_id: str, **kw):
    with jobs_lock:
        jobs[job_id].update(kw)


def _log(job_id: str, msg: str):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(f"[{job_id}] {msg}", flush=True)
    with jobs_lock:
        logs = jobs[job_id]["logs"]
        logs.append(line)
        del logs[:-MAX_LOG_LINES]


def _worker():
    while True:
        job_id = job_queue.get()
        job = jobs[job_id]
        _update(job_id, status="running", started_at=time.time())
        try:
            token, _ = config.load_token()
            meta = download_course(
                job["url"], token, config.COURSES_DIR, job["langs"], force=job["force"], resources=job["resources"],
                workers=config.WORKERS,
                log=lambda m: _log(job_id, m),
                progress=lambda d, t: _update(job_id, done=d, total=t),
            )
            _update(job_id, status="done", slug=meta["slug"], stats=meta["stats"])
        except Exception as e:
            _log(job_id, t("log_job_failed", err=e))
            _update(job_id, status="error", error=str(e))
        finally:
            _update(job_id, finished_at=time.time())
            job_queue.task_done()


threading.Thread(target=_worker, daemon=True).start()


# ── Routes ──────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


def require_app_header(x_requested_with: str | None = Header(default=None)):
    """POST không có body JSON là "simple request" — trang web lạ submit được bằng form ẩn.
    Bắt header riêng → trình duyệt buộc preflight CORS, mà app không bật CORS → bị chặn.
    (POST có body JSON đã an toàn sẵn: FastAPI chỉ parse body khi Content-Type là application/json.)"""
    if x_requested_with != APP_HEADER:
        raise HTTPException(403, t("api_missing_header"))


@app.get("/api/app-info")
def app_info():
    """launcher.py dùng để nhận ra phiên portable đang chạy (tránh mở 2 server)."""
    return {"app": APP_HEADER, "portable": config.PORTABLE,
            "data_dir": config.display_path(config.DATA_DIR.resolve()) if config.PORTABLE else None}


@app.post("/api/shutdown", dependencies=[Depends(require_app_header)])
def shutdown():
    if not config.PORTABLE:
        raise HTTPException(403, t("api_shutdown_docker"))
    threading.Timer(0.5, lambda: os._exit(0)).start()  # trả response trước rồi mới tắt
    return {"ok": True}


@app.post("/api/open-folder", dependencies=[Depends(require_app_header)])
def open_folder(slug: str | None = None):
    """Mở thư mục khoá (hoặc thư mục dữ liệu) bằng Explorer — chỉ bản portable trên Windows."""
    if not config.PORTABLE or not hasattr(os, "startfile"):
        raise HTTPException(403, t("api_portable_only"))
    if slug:
        path = _course_dir(slug)
    else:
        path = config.COURSES_DIR
        path.mkdir(parents=True, exist_ok=True)
    os.startfile(config.display_path(path))  # Explorer không hiểu tiền tố \\?\
    return {"ok": True, "path": config.display_path(path)}


class SettingsIn(BaseModel):
    ui_lang: str


def rerender_courses() -> int:
    """Đổi ngôn ngữ giao diện → dựng lại OVERVIEW.md (từ overview.json) + trang HTML của mọi khoá
    đã tải, để trang đọc không lẫn 2 thứ tiếng. Không gọi Udemy. Các .md khác (CONTENTS, INDEX,
    transcript gộp) đổi theo ở lần bấm Cập nhật kế tiếp."""
    from render import render_course
    from udemy import write_overview

    done = 0
    for meta_file in config.COURSES_DIR.glob("*/course.json") if config.COURSES_DIR.exists() else []:
        course_dir = meta_file.parent
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            details_file = course_dir / "overview.json"
            if details_file.exists() and meta.get("host"):
                write_overview(course_dir, meta["host"], json.loads(details_file.read_text(encoding="utf-8")))
            if meta.get("outline"):
                render_course(course_dir, meta)
                done += 1
        except (OSError, ValueError) as e:
            print(f"[settings] rerender {course_dir.name}: {e}", flush=True)
    return done


@app.get("/api/settings")
def get_settings():
    """`saved=false` → người dùng chưa chọn lần nào, web UI tự đoán theo ngôn ngữ trình duyệt rồi lưu."""
    return {"ui_lang": i18n.get_lang(), "saved": i18n.saved_lang() is not None, "langs": list(i18n.LANGS)}


@app.post("/api/settings")
def update_settings(body: SettingsIn):
    lang = body.ui_lang.strip().lower()
    if lang not in i18n.LANGS:
        raise HTTPException(400, t("api_bad_ui_lang"))
    changed = lang != i18n.get_lang() or i18n.saved_lang() is None
    i18n.set_lang(lang)
    rerendered = rerender_courses() if changed else 0
    return {**get_settings(), "rerendered": rerendered}


class TokenIn(BaseModel):
    token: str


@app.get("/api/token")
def token_status(check: bool = False):
    """Không bao giờ trả lại token — chỉ nguồn và (nếu check=1) kết quả gọi /users/me."""
    token, source = config.load_token()
    out = {"source": source, "configured": bool(token)}
    if check and token:
        try:
            me = UdemyClient("www.udemy.com", token).me()
            out.update(valid=True, user=me.get("display_name") or me.get("title") or me.get("name"))
        except UdemyError as e:
            out.update(valid=False, error=str(e))
    return out


@app.post("/api/token")
def set_token(body: TokenIn):
    if not body.token.strip():
        raise HTTPException(400, t("api_token_empty"))
    config.save_token(body.token)
    return token_status(check=True)


@app.delete("/api/token")
def delete_token():
    config.clear_token()
    return token_status()


class JobIn(BaseModel):
    url: str
    langs: list[str] | None = None
    force: bool = False
    resources: bool = True


@app.post("/api/jobs")
def create_job(body: JobIn):
    try:
        _, slug = parse_course_url(body.url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    langs = [x.strip().lower() for x in (body.langs or config.DEFAULT_LANGS) if x.strip()]
    if not langs or not all(LANG_RE.match(x) for x in langs):
        raise HTTPException(400, t("api_bad_langs"))
    job_id = uuid.uuid4().hex[:10]
    with jobs_lock:
        jobs[job_id] = {
            "id": job_id, "url": body.url.strip(), "slug": slug, "langs": langs, "force": body.force, "resources": body.resources,
            "status": "queued", "done": 0, "total": 0, "logs": [], "error": None, "stats": None,
            "created_at": time.time(), "started_at": None, "finished_at": None,
        }
        snapshot = dict(jobs[job_id], logs=[])  # worker có thể sửa job ngay sau put()
    job_queue.put(job_id)
    return snapshot


@app.get("/api/jobs")
def list_jobs():
    with jobs_lock:
        items = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)[:20]
        return [{k: v for k, v in j.items() if k != "logs"} for j in items]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(404, t("api_no_job"))
        return dict(jobs[job_id], logs=list(jobs[job_id]["logs"]))


def _course_dir(slug: str) -> Path:
    root = config.COURSES_DIR.resolve()
    path = (root / slug).resolve()
    if path.parent != root or not (path / "course.json").exists():
        raise HTTPException(404, t("api_no_course"))
    return path


@app.get("/api/courses")
def list_courses():
    out = []
    if config.COURSES_DIR.exists():
        for meta_file in config.COURSES_DIR.glob("*/course.json"):
            try:
                out.append(json.loads(meta_file.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda m: m.get("updated_at", 0), reverse=True)


@app.get("/api/courses/{slug}/transcript/{lang}")
def course_transcript(slug: str, lang: str, download: bool = False):
    if not LANG_RE.match(lang):
        raise HTTPException(400, t("api_bad_lang"))
    path = _course_dir(slug) / f"transcript.{lang}.md"
    if not path.exists():
        raise HTTPException(404, t("api_no_transcript"))
    if download:
        return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{slug}.{lang}.md")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/api/courses/{slug}/overview")
def course_overview(slug: str, download: bool = False):
    path = _course_dir(slug) / "OVERVIEW.md"
    if not path.exists():
        raise HTTPException(404, t("api_no_overview"))
    if download:
        return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=f"{slug}.overview.md")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/view/{slug}")
def view_redirect(slug: str):
    _course_dir(slug)
    return RedirectResponse(f"/view/{quote(slug)}/")  # có dấu / cuối thì link tương đối trong trang mới đúng


@app.get("/view/{slug}/{path:path}")
def view_file(slug: str, path: str = ""):
    root = _course_dir(slug)
    target = (root / (path or "index.html")).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, t("api_no_file") if path else t("api_no_html"))
    resp = FileResponse(target)
    if target.suffix.lower() in (".html", ".htm"):
        resp.headers["Content-Security-Policy"] = VIEW_CSP
    return resp


@app.get("/api/courses/{slug}/zip")
def course_zip(slug: str):
    course_dir = _course_dir(slug)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(course_dir.rglob("*")):
            if f.is_file():
                zf.write(f, Path(slug) / f.relative_to(course_dir))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'})
