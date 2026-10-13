"""Bảng dịch EN/VI cho mọi chữ hiển thị cho người dùng: log job, thông báo lỗi, file .md/.html
sinh ra, CLI. (Web UI có bảng riêng trong static/index.html; launcher portable có bảng riêng vì
chạy trước khi nạp app.)

Ngôn ngữ GIAO DIỆN — độc lập với ngôn ngữ PHỤ ĐỀ cần tải (en/vi/ja... trong `langs` của job).
Thứ tự ưu tiên: data/settings.json (nút EN|VI trên web) → biến môi trường APP_LANG → "en".
"""
import json
import os
import string
import threading
from pathlib import Path

LANGS = ("en", "vi")
DEFAULT = "en"
_lock = threading.Lock()
_cache: dict[str, str | None] = {}  # đường dẫn settings.json → ngôn ngữ đã lưu


def _settings_file() -> Path:
    import config  # import muộn: config.DATA_DIR bị test monkeypatch
    return config.DATA_DIR / "settings.json"


def _read_settings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def saved_lang() -> str | None:
    """Ngôn ngữ người dùng đã chọn; None nếu chưa chọn lần nào (web UI sẽ đoán theo trình duyệt)."""
    path = _settings_file()
    key = str(path)
    with _lock:
        if key not in _cache:
            lang = _read_settings(path).get("ui_lang")
            _cache[key] = lang if lang in LANGS else None
        return _cache[key]


def get_lang() -> str:
    lang = saved_lang() or os.environ.get("APP_LANG", "").strip().lower()
    return lang if lang in LANGS else DEFAULT


def set_lang(lang: str):
    if lang not in LANGS:
        raise ValueError(lang)
    path = _settings_file()
    with _lock:
        data = _read_settings(path)
        data["ui_lang"] = lang
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _cache[str(path)] = lang


def t(key: str, ui_lang: str | None = None, **kw) -> str:
    # Tham số tên ui_lang (không phải lang): nhiều message có placeholder {lang} = mã ngôn ngữ PHỤ ĐỀ
    entry = MESSAGES[key]
    text = entry.get(ui_lang or get_lang()) or entry[DEFAULT]
    return text.format(**kw) if kw else text


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


MESSAGES: dict[str, dict[str, str]] = {
    # ── Nhập liệu ───────────────────────────────────────────
    "url_not_udemy": {"en": "Not a udemy.com URL", "vi": "URL không phải của udemy.com"},
    "url_no_course": {"en": "URL must look like .../course/<course-name>/",
                      "vi": "URL không có dạng .../course/<tên-khoá>/"},

    # ── Lỗi Udemy / mạng ────────────────────────────────────
    "no_token": {
        "en": "No access_token yet — paste the access_token cookie in the web UI or set UDEMY_ACCESS_TOKEN in .env",
        "vi": "Chưa có access_token — dán cookie access_token ở giao diện web hoặc đặt UDEMY_ACCESS_TOKEN trong .env"},
    "foreign_host": {"en": "Refusing to send the token to a foreign host: {url}",
                     "vi": "Từ chối gửi token tới host lạ: {url}"},
    "token_401": {"en": "Invalid or expired token (401) — get a fresh access_token cookie",
                  "vi": "Token không hợp lệ hoặc đã hết hạn (401) — lấy lại cookie access_token"},
    "cloudflare_403": {
        "en": "Blocked by Cloudflare (403) — try pasting the full Cookie header (with cf_clearance) instead of just access_token",
        "vi": "Bị Cloudflare chặn (403) — thử dán nguyên chuỗi Cookie header (có cf_clearance) thay vì chỉ access_token"},
    "forbidden_403": {"en": "Access denied (403) — wrong token, or this account doesn't own the course",
                      "vi": "Không có quyền truy cập (403) — token sai hoặc tài khoản chưa sở hữu khoá này"},
    "not_json": {"en": "Udemy returned HTML instead of JSON (blocked by Cloudflare, or not logged in)",
                 "vi": "Udemy trả về HTML thay vì JSON (có thể bị Cloudflare chặn hoặc chưa đăng nhập)"},
    "course_not_found": {"en": "Course '{slug}' not found in this account",
                         "vi": "Không tìm thấy khoá '{slug}' trong tài khoản này"},
    "no_download_link": {"en": "Udemy returned no download link for this file",
                         "vi": "Udemy không trả link tải cho file này"},
    "caption_http": {"en": "Caption download failed: HTTP {status}", "vi": "Tải phụ đề lỗi HTTP {status}"},
    "file_http": {"en": "File download failed: HTTP {status}", "vi": "Tải file lỗi HTTP {status}"},
    "invalid_token": {"en": "Invalid or expired token — get a fresh access_token cookie ({err})",
                      "vi": "Token không hợp lệ hoặc đã hết hạn — lấy lại cookie access_token ({err})"},

    # ── Log job ─────────────────────────────────────────────
    "log_finding": {"en": "Looking up course '{slug}' on {host}...", "vi": "Đang tìm khoá '{slug}' trên {host}..."},
    "log_course": {"en": "Course #{id}: {title}", "vi": "Khoá #{id}: {title}"},
    "log_structure": {"en": "{chapters} sections, {lectures} video lectures",
                      "vi": "{chapters} chương, {lectures} bài video"},
    "log_overview_saved": {"en": "Saved course overview (OVERVIEW.md)", "vi": "Đã lưu tổng quan khoá (OVERVIEW.md)"},
    "log_overview_failed": {"en": "WARNING: could not fetch the course overview: {err}",
                            "vi": "CẢNH BÁO: không lấy được tổng quan khoá: {err}"},
    "log_captions": {
        "en": "[{lang}] captions for {available}/{total} lectures ({auto} auto), already downloaded {skipped}",
        "vi": "[{lang}] có phụ đề {available}/{total} bài ({auto} auto), đã có sẵn {skipped}"},
    "log_file_error": {"en": "[file] ERROR {name}: {err}", "vi": "[file] LỖI {name}: {err}"},
    "log_files": {"en": "[file] {files} attached files ({links} external links), already downloaded {skipped}",
                  "vi": "[file] {files} file đính kèm ({links} link ngoài), đã có sẵn {skipped}"},
    "log_task_error": {"en": "ERROR {label}: {err}", "vi": "LỖI {label}: {err}"},
    "log_html_done": {"en": "Built browser reading pages: {pages}", "vi": "Đã dựng trang đọc trên trình duyệt: {pages}"},
    "log_html_failed": {"en": "WARNING: could not build HTML: {err}", "vi": "CẢNH BÁO: không dựng được HTML: {err}"},
    "log_lang_done": {
        "en": "[{lang}] done: downloaded {downloaded}, skipped {skipped}, failed {failed}, no captions {missing}",
        "vi": "[{lang}] xong: tải {downloaded}, bỏ qua {skipped}, lỗi {failed}, không có phụ đề {missing}"},
    "log_files_done": {"en": "[file] done: downloaded {downloaded}, skipped {skipped}, failed {failed}",
                       "vi": "[file] xong: tải {downloaded}, bỏ qua {skipped}, lỗi {failed}"},
    "log_job_failed": {"en": "FAILED: {err}", "vi": "THẤT BẠI: {err}"},

    # ── File markdown sinh ra ───────────────────────────────
    "md_no_section": {"en": "(No section)", "vi": "(Không thuộc chương nào)"},
    "md_resources_title": {"en": "{title} — attached resources", "vi": "{title} — tài nguyên đính kèm"},
    "md_not_downloaded": {"en": "not downloaded", "vi": "chưa tải được"},
    "ov_instructors": {"en": "Instructors", "vi": "Giảng viên"},
    "ov_category": {"en": "Category", "vi": "Danh mục"},
    "ov_level": {"en": "Level", "vi": "Trình độ"},
    "ov_language": {"en": "Language", "vi": "Ngôn ngữ"},
    "ov_length": {"en": "Length", "vi": "Thời lượng"},
    "ov_lectures": {"en": "{n} lectures", "vi": "{n} bài"},
    "ov_rating": {"en": "Rating", "vi": "Đánh giá"},
    "ov_reviews": {"en": "{n} ratings", "vi": "{n} đánh giá"},
    "ov_students": {"en": "{n} students", "vi": "{n} học viên"},
    "ov_captions": {"en": "Captions", "vi": "Phụ đề"},
    "ov_updated": {"en": "Last updated", "vi": "Cập nhật"},
    "ov_link": {"en": "Link", "vi": "Link"},
    "ov_learn": {"en": "What you'll learn", "vi": "Bạn sẽ học được gì"},
    "ov_requirements": {"en": "Requirements", "vi": "Yêu cầu"},
    "ov_description": {"en": "Description", "vi": "Mô tả"},
    "ov_audience": {"en": "Who this course is for", "vi": "Khoá học này dành cho ai"},

    # ── Trang HTML (render.py) ──────────────────────────────
    "html_back": {"en": "← Course home", "vi": "← Trang khoá"},
    "html_intro_section": {"en": "Introduction", "vi": "Mở đầu"},
    "html_not_downloaded": {"en": "not downloaded", "vi": "chưa tải được"},
    "html_updated": {"en": "Updated {date}", "vi": "Cập nhật {date}"},
    "html_counts": {"en": "{chapters} sections · {lectures} video lectures",
                    "vi": "{chapters} chương · {lectures} bài video"},
    "html_files": {"en": "{n} attached files", "vi": "{n} file đính kèm"},
    "html_overview_btn": {"en": "Course overview", "vi": "Tổng quan khoá"},
    "html_machine_suffix": {"en": " (machine-translated)", "vi": " (dịch máy)"},
    "html_open_udemy": {"en": "Open on Udemy ↗", "vi": "Mở trên Udemy ↗"},
    "html_chip_auto": {"en": "machine-translated captions", "vi": "phụ đề dịch máy"},
    "html_chip_manual": {"en": "original captions", "vi": "phụ đề gốc"},
    "html_chip_none": {"en": "no captions", "vi": "không có phụ đề"},
    "html_overview_title": {"en": "Overview — {title}", "vi": "Tổng quan — {title}"},
    "html_badge_auto": {"en": "machine-translated", "vi": "dịch máy"},
    "html_all_auto_note": {
        "en": "All captions in this language are Udemy's <b>machine translation</b> — terminology may be off, "
              "check the original when needed.",
        "vi": "Toàn bộ phụ đề ngôn ngữ này là bản <b>dịch máy</b> của Udemy — có thể sai thuật ngữ, "
              "đối chiếu bản gốc khi cần."},
    "html_toc": {"en": "Contents · {n} lectures", "vi": "Mục lục · {n} bài"},
    "html_back_to_top": {"en": "↑ Back to top", "vi": "↑ Lên đầu trang"},
    "kind_article": {"en": "Article", "vi": "Bài đọc"},
    "kind_file": {"en": "Document", "vi": "Tài liệu"},
    "html_no_outline": {
        "en": "course.json has no outline (downloaded by an older version) — click Update to re-download",
        "vi": "course.json chưa có outline (khoá tải bằng bản cũ) — bấm Cập nhật để tải lại"},
    "render_error": {"en": "{name}: ERROR {err}", "vi": "{name}: LỖI {err}"},

    # ── API (main.py) ───────────────────────────────────────
    "api_missing_header": {"en": "Missing X-Requested-With header", "vi": "Thiếu header X-Requested-With"},
    "api_shutdown_docker": {"en": "Only the portable build can be shut down — for Docker use docker compose stop",
                            "vi": "Chỉ tắt được bản portable — bản Docker dùng docker compose stop"},
    "api_portable_only": {"en": "Only available in the Windows portable build", "vi": "Chỉ có ở bản Windows portable"},
    "api_token_empty": {"en": "Empty token", "vi": "Token trống"},
    "api_bad_langs": {"en": "Invalid language code (e.g. en, vi)", "vi": "Mã ngôn ngữ không hợp lệ (vd: en, vi)"},
    "api_bad_lang": {"en": "Invalid language code", "vi": "Mã ngôn ngữ không hợp lệ"},
    "api_bad_ui_lang": {"en": "Unsupported interface language (en, vi)", "vi": "Ngôn ngữ giao diện không hỗ trợ (en, vi)"},
    "api_no_job": {"en": "No such job", "vi": "Không có job này"},
    "api_no_course": {"en": "No such course", "vi": "Không có khoá này"},
    "api_no_transcript": {"en": "This course has no transcript in that language",
                          "vi": "Khoá này không có transcript ngôn ngữ này"},
    "api_no_overview": {"en": "This course has no overview yet — click Update to re-download",
                        "vi": "Khoá này chưa có tổng quan — bấm Cập nhật để tải lại"},
    "api_no_file": {"en": "File not found", "vi": "Không có file này"},
    "api_no_html": {"en": "This course has no HTML pages yet — click Update",
                    "vi": "Khoá này chưa có trang HTML — bấm Cập nhật"},

    # ── CLI ─────────────────────────────────────────────────
    "cli_description": {"en": "Download transcripts of one Udemy course", "vi": "Tải transcript 1 khoá Udemy"},
    "cli_force": {"en": "re-download lectures that already exist", "vi": "tải lại cả bài đã có"},
    "cli_no_resources": {"en": "skip attached files (pdf, docx...)", "vi": "không tải file đính kèm (pdf, docx...)"},
    "cli_error": {"en": "Error: {err}", "vi": "Lỗi: {err}"},
    "cli_done": {"en": "Done → {path}", "vi": "Xong → {path}"},
}
