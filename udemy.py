"""Udemy API client + chuyển phụ đề VTT thành transcript.

Ý tưởng lấy từ TOA-Anakin/udemy-transcript-downloader, nhưng bỏ bước mở
trình duyệt và bấm nút "Transcript" của repo gốc: API curriculum vốn đã trả về
URL phụ đề VTT của từng bài giảng, mà transcript panel của Udemy chính là
phụ đề đó. Tải thẳng VTT nhanh hơn nhiều và không vỡ khi Udemy đổi giao diện.
"""
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from i18n import t

IMPERSONATE = "chrome"  # curl_cffi giả TLS fingerprint của Chrome để qua Cloudflare
MAX_CURRICULUM_PAGES = 100
MAX_COURSE_SCAN_PAGES = 50
COURSE_DETAIL_FIELDS = (
    "title,headline,description,what_you_will_learn_data,objectives,requirements_data,prerequisites,"
    "target_audiences,visible_instructors,content_info,num_lectures,locale,last_update_date,"
    "primary_category,primary_subcategory,instructional_level_simple,rating,num_reviews,num_subscribers,"
    "caption_languages,url"
)


class UdemyError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AuthError(UdemyError):
    pass


class NotFoundError(UdemyError):
    pass


# ── Parse input ─────────────────────────────────────────────

_COURSE_PATH_RE = re.compile(r"/course/([^/?#]+)")


def parse_course_url(url: str) -> tuple[str, str]:
    """Trả (host, slug). Chỉ chấp nhận udemy.com và subdomain (Udemy Business)
    để token không bao giờ bị gửi tới host lạ."""
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host == "udemy.com":
        host = "www.udemy.com"
    if not host.endswith(".udemy.com"):
        raise ValueError(t("url_not_udemy"))
    m = _COURSE_PATH_RE.search(parsed.path)
    if not m:
        raise ValueError(t("url_no_course"))
    return host, m.group(1)


def parse_token(raw: str) -> tuple[str, dict]:
    """Nhận token trần, hoặc nguyên chuỗi Cookie header copy từ DevTools.
    Trả (access_token, cookies)."""
    raw = (raw or "").strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):].strip()
    if ";" in raw or raw.startswith("access_token="):
        cookies = {}
        for part in raw.split(";"):
            k, sep, v = part.strip().partition("=")
            if sep and k.strip():
                cookies[k.strip()] = v.strip()
        return cookies.get("access_token", ""), cookies
    return raw, ({"access_token": raw} if raw else {})


_INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = _INVALID_FS_CHARS.sub("-", name or "")
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:max_len].rstrip(" .")  # Windows không cho tên kết thúc bằng dấu chấm/khoảng trắng
    return name or "untitled"


# ── VTT → SRT / text ────────────────────────────────────────

@dataclass
class Cue:
    start: float
    end: float
    text: str


_TS_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})$")
_TAG_RE = re.compile(r"<[^>]*>")


def _parse_ts(s: str) -> float:
    m = _TS_RE.match(s.strip())
    if not m:
        raise ValueError(f"invalid timestamp: {s!r}")
    h, mnt, sec, ms = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(sec) + int(ms.ljust(3, "0")) / 1000


def parse_vtt(text: str) -> list[Cue]:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n[ \t]*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if idx is None:
            continue  # header WEBVTT, NOTE, STYLE, REGION
        start_s, _, rest = lines[idx].partition("-->")
        rest = rest.split()
        if not rest:
            continue
        try:
            start, end = _parse_ts(start_s), _parse_ts(rest[0])  # bỏ cue settings (align:, position:)
        except ValueError:
            continue
        body = html.unescape(_TAG_RE.sub("", "\n".join(lines[idx + 1:]))).strip()
        if body:
            cues.append(Cue(start, end, body))
    return cues


def _fmt_srt_ts(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cues_to_srt(cues: list[Cue]) -> str:
    return "\n".join(
        f"{i}\n{_fmt_srt_ts(c.start)} --> {_fmt_srt_ts(c.end)}\n{c.text}\n"
        for i, c in enumerate(cues, 1)
    )


_SENTENCE_END = (".", "?", "!", "…", '"', "”")


def cues_to_text(cues: list[Cue], para_gap: float = 2.0, para_chars: int = 700) -> str:
    """Nối cue thành đoạn văn. Ngắt đoạn khi câu kết thúc VÀ (có khoảng lặng
    dài hoặc đoạn đã quá dài) — phụ đề Udemy thường liền mạch không có gap."""
    paras, cur, cur_len = [], [], 0
    prev_end, last = None, None
    for c in cues:
        line = " ".join(c.text.split())
        if line == last:
            continue  # auto-caption đôi khi lặp lại y hệt cue trước
        if cur and cur[-1].endswith(_SENTENCE_END) and (
            (prev_end is not None and c.start - prev_end >= para_gap) or cur_len >= para_chars
        ):
            paras.append(" ".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
        last, prev_end = line, c.end
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


# ── HTML → Markdown (mô tả khoá học) ────────────────────────

_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _MarkdownParser(HTMLParser):
    """Đủ cho HTML mô tả khoá Udemy: p/div, heading, ul/ol lồng nhau, strong/em, a, br."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.lists, self.hrefs, self.bol = [], [], [], True

    def _break(self, text):
        self.out.append(text)
        self.bol = True

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "div", "blockquote"):
            self._break("\n\n")
        elif tag in _HEADINGS:
            # mô tả nằm dưới "## Mô tả" của OVERVIEW.md → hạ heading xuống từ cấp 3
            self._break("\n\n" + "#" * min(int(tag[1]) + 2, 6) + " ")
        elif tag in ("ul", "ol"):
            if not self.lists:
                self._break("\n\n")
            self.lists.append([tag, 0])
        elif tag == "li":
            kind = self.lists[-1] if self.lists else ["ul", 0]
            kind[1] += 1
            marker = "- " if kind[0] == "ul" else f"{kind[1]}. "
            self._break("\n" + "  " * max(len(self.lists) - 1, 0) + marker)
        elif tag == "br":
            self._break("\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a":
            self.hrefs.append(dict(attrs).get("href"))
            self.out.append("[")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "blockquote") or tag in _HEADINGS:
            self._break("\n\n")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            if not self.lists:
                self._break("\n\n")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a":
            href = self.hrefs.pop() if self.hrefs else None
            self.out.append(f"]({href})" if href else "]")

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data)
        if self.bol:
            text = text.lstrip()
        if text:
            self.out.append(text)
            self.bol = False


def html_to_markdown(source: str) -> str:
    parser = _MarkdownParser()
    parser.feed(source or "")
    parser.close()
    text = "".join(parser.out)
    text = re.sub(r"\*\*\s*\*\*", "", text)       # <strong></strong> rỗng
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Curriculum ──────────────────────────────────────────────

@dataclass
class Lecture:
    id: int
    title: str
    chapter_index: int  # 0 = bài nằm trước chương đầu tiên
    chapter_title: str
    index_in_chapter: int
    duration: int  # giây
    captions: list = field(default_factory=list)

    @property
    def number(self) -> str:
        return f"{self.chapter_index:02d}.{self.index_in_chapter:02d}"

    @property
    def stem(self) -> str:
        return sanitize_filename(f"{self.number} {self.title}")


@dataclass
class Chapter:
    index: int
    title: str
    lectures: list = field(default_factory=list)


def _ordered(items: list[dict]) -> list[dict]:
    if items and all(isinstance(it.get("sort_order"), (int, float)) for it in items):
        # Udemy đánh sort_order giảm dần theo thứ tự hiển thị (giống repo gốc)
        return sorted(items, key=lambda it: it["sort_order"], reverse=True)
    return items


def build_structure(items: list[dict]) -> list[Chapter]:
    """Gom item curriculum thành chương/bài. Chỉ lấy lecture dạng video
    (bài article/quiz/practice không có phụ đề)."""
    chapters: list[Chapter] = []
    loose = Chapter(0, "")
    current = loose
    for it in _ordered(items):
        cls = it.get("_class")
        if cls == "chapter":
            current = Chapter(len(chapters) + 1, it.get("title") or "")
            chapters.append(current)
        elif cls == "lecture":
            asset = it.get("asset") or {}
            if "video" not in str(asset.get("asset_type") or "").lower():
                continue
            current.lectures.append(Lecture(
                id=it["id"],
                title=it.get("title") or f"Lecture {it['id']}",
                chapter_index=current.index,
                chapter_title=current.title,
                index_in_chapter=len(current.lectures) + 1,
                duration=int(asset.get("time_estimation") or 0),
                captions=[c for c in (asset.get("captions") or []) if c.get("url")],
            ))
    return ([loose] if loose.lectures else []) + chapters


@dataclass
class Resource:
    """File/link đính kèm của 1 bài (supplementary asset) — bài video lẫn article đều có."""
    lecture_id: int
    lecture_title: str
    chapter_index: int
    chapter_title: str
    asset: dict

    @property
    def is_link(self) -> bool:
        return str(self.asset.get("asset_type") or "").lower() == "externallink"

    @property
    def folder(self) -> str:
        return sanitize_filename(f"{self.chapter_index:02d} {self.chapter_title}")

    @property
    def filename(self) -> str:
        # `title` là tên file gốc lúc upload (vd Workbook_v2.docx), `filename` là bản Udemy đã đổi
        # `_` → `-`. Dùng title nếu nó có cùng đuôi file, không thì dùng filename.
        title, fname = str(self.asset.get("title") or ""), str(self.asset.get("filename") or "")
        suffix = Path(fname).suffix or Path(title).suffix
        name = title if suffix and title.lower().endswith(suffix.lower()) else (fname or title)
        name = name or f"asset-{self.asset.get('id')}"
        if suffix and name.lower().endswith(suffix.lower()):
            # 100 ký tự: Word/Excel không mở được file có đường dẫn > 260 ký tự trên Windows
            return sanitize_filename(name[: -len(suffix)], max_len=100 - len(suffix)) + suffix
        return sanitize_filename(name, max_len=100)


def collect_resources(items: list[dict]) -> list[Resource]:
    out, chapter_index, chapter_title = [], 0, ""
    for it in _ordered(items):
        cls = it.get("_class")
        if cls == "chapter":
            chapter_index, chapter_title = chapter_index + 1, it.get("title") or ""
        elif cls == "lecture":
            for asset in it.get("supplementary_assets") or []:
                if asset.get("id"):
                    out.append(Resource(it["id"], it.get("title") or f"Lecture {it['id']}",
                                        chapter_index, chapter_title, asset))
    return out


def caption_lang(caption: dict) -> str:
    return str(caption.get("locale_id") or "").lower().replace("-", "_").split("_")[0]


def is_auto_caption(caption: dict) -> bool:
    return (
        str(caption.get("source") or "").lower() == "auto"
        or "[auto]" in str(caption.get("title") or "").lower()
        or "auto" in str(caption.get("video_label") or "").lower()
    )


def pick_caption(captions: list[dict], lang: str) -> dict | None:
    """Chọn phụ đề cho 1 ngôn ngữ, ưu tiên bản do giảng viên upload hơn bản auto."""
    lang = lang.lower()
    cands = [c for c in captions if c.get("url") and caption_lang(c) == lang]
    if not cands:
        return None
    return sorted(cands, key=is_auto_caption)[0]


# ── HTTP ────────────────────────────────────────────────────

class UdemyClient:
    def __init__(self, host: str, token_raw: str, timeout: int = 30):
        token, cookies = parse_token(token_raw)
        if not token:
            raise AuthError(t("no_token"))
        from curl_cffi import requests as cffi_requests

        self.host = host
        self.base = f"https://{host}"
        self.session = cffi_requests.Session(impersonate=IMPERSONATE, timeout=timeout)
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "X-Udemy-Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
            "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        })

    def _get(self, url: str, params: dict | None = None):
        if url.startswith("/"):
            url = self.base + url
        elif (urlparse(url).hostname or "").lower() != self.host:
            raise UdemyError(t("foreign_host", url=url))
        resp = None
        for attempt in range(4):
            resp = self.session.get(url, params=params)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt * 2)
                continue
            break
        if resp.status_code == 401:
            raise AuthError(t("token_401"), 401)
        if resp.status_code == 403:
            head = resp.text[:3000].lower()
            if "cloudflare" in head or "cf-chl" in head or "just a moment" in head:
                raise UdemyError(t("cloudflare_403"))
            raise AuthError(t("forbidden_403"), 403)
        if resp.status_code == 404:
            raise NotFoundError(f"404: {url}", 404)
        if resp.status_code >= 400:
            raise UdemyError(f"HTTP {resp.status_code}: {url}", resp.status_code)
        return resp

    def get_json(self, url: str, params: dict | None = None) -> dict:
        resp = self._get(url, params)
        try:
            return resp.json()
        except ValueError:
            raise UdemyError(t("not_json"))

    def me(self) -> dict:
        return self.get_json("/api-2.0/users/me/")

    def _paginate(self, url: str, params: dict | None, max_pages: int):
        pages = 0
        while url and pages < max_pages:
            data = self.get_json(url, params)
            yield from data.get("results") or []
            url, params = data.get("next"), None  # `next` đã chứa sẵn query
            pages += 1

    @staticmethod
    def _matches(course: dict, slug: str) -> bool:
        return course.get("published_title") == slug or f"/course/{slug}/" in str(course.get("url") or "")

    def resolve_course(self, slug: str) -> dict:
        """slug → {id, title, published_title}. Thử lần lượt, nguồn nào lỗi (trừ 401) thì sang nguồn sau:
        1. /courses/<slug>/ — API nhận thẳng slug (chạy cả trên Udemy Business)
        2. quét toàn bộ khoá đã mua — KHÔNG dùng ?search=: Udemy Business trả 500 với tham số này
        3. khoá thuộc gói Personal Plan (tài khoản không có gói trả rỗng/403/404)
        4. data-clp-course-id trên trang khoá (cách của repo gốc; trang Business không có)"""
        try:
            c = self.get_json(f"/api-2.0/courses/{slug}/", {"fields[course]": "id,title"})
            if c.get("id"):
                return {"id": c["id"], "title": c.get("title") or slug, "published_title": slug}
        except UdemyError as e:
            if e.status == 401:
                raise
        fields = {"fields[course]": "id,title,published_title,url"}
        sources = [
            ("/api-2.0/users/me/subscribed-courses/", {**fields, "page_size": 100}),
            ("/api-2.0/users/me/subscription-course-enrollments/", {**fields, "page_size": 50, "search": slug}),
        ]
        for path, params in sources:
            try:
                for c in self._paginate(path, params, MAX_COURSE_SCAN_PAGES):
                    if self._matches(c, slug):
                        return {"id": c["id"], "title": c.get("title") or slug, "published_title": slug}
            except UdemyError as e:
                if e.status == 401:
                    raise
        try:
            html_text = self._get(f"/course/{slug}/").text
        except UdemyError as e:
            if e.status == 401:
                raise
            html_text = ""
        m = re.search(r'data-clp-course-id="(\d+)"', html_text)
        if not m:
            raise NotFoundError(t("course_not_found", slug=slug))
        course_id = int(m.group(1))
        try:
            title = self.get_json(f"/api-2.0/courses/{course_id}/", {"fields[course]": "title"}).get("title")
        except UdemyError:
            title = None
        return {"id": course_id, "title": title or slug, "published_title": slug}

    def course_details(self, course_id: int) -> dict:
        """Phần "tổng quan" của trang khoá: headline, mô tả, bạn sẽ học được gì, yêu cầu, đối tượng..."""
        return self.get_json(f"/api-2.0/courses/{course_id}/", {"fields[course]": COURSE_DETAIL_FIELDS})

    def curriculum(self, course_id: int) -> list[dict]:
        params = {
            "page_size": 200,
            "fields[lecture]": "title,object_index,sort_order,asset,supplementary_assets",
            "fields[chapter]": "title,object_index,sort_order",
            # fields[asset] áp cho cả asset chính lẫn supplementary_assets
            "fields[asset]": "asset_type,time_estimation,captions,title,filename,external_url",
            "caching_intent": "True",
        }
        return list(self._paginate(
            f"/api-2.0/courses/{course_id}/subscriber-curriculum-items/", params, MAX_CURRICULUM_PAGES
        ))

    def asset_download_url(self, course_id: int, lecture_id: int, asset_id: int) -> str:
        """Link CDN (att-c.udemycdn.com) đã ký, hết hạn sau một thời gian — lấy ngay trước khi tải.
        /api-2.0/assets/<id>/ trả 403 với file đính kèm, phải đi qua đường dẫn của bài."""
        data = self.get_json(
            f"/api-2.0/users/me/subscribed-courses/{course_id}/lectures/{lecture_id}/supplementary-assets/{asset_id}/",
            {"fields[asset]": "download_urls"},
        )
        for entries in (data.get("download_urls") or {}).values():
            for entry in entries or []:
                if entry.get("file"):
                    return entry["file"]
        raise UdemyError(t("no_download_link"))


def fetch_vtt(url: str, timeout: int = 30) -> str:
    """URL phụ đề là link CDN đã ký sẵn — không cần (và không gửi) token."""
    from curl_cffi import requests as cffi_requests

    resp = cffi_requests.get(url, impersonate=IMPERSONATE, timeout=timeout)
    if resp.status_code >= 400:
        raise UdemyError(t("caption_http", status=resp.status_code))
    return resp.content.decode("utf-8-sig", errors="replace")


def fetch_file(url: str, dest: Path, timeout: int = 300):
    """Stream về file .part rồi mới đổi tên — tải dở không bị nhận nhầm là đã có."""
    from curl_cffi import requests as cffi_requests

    part = dest.with_name(dest.name + ".part")
    resp = cffi_requests.get(url, impersonate=IMPERSONATE, timeout=timeout, stream=True)
    try:
        if resp.status_code >= 400:
            raise UdemyError(t("file_http", status=resp.status_code))
        with open(part, "wb") as f:
            for chunk in resp.iter_content():
                f.write(chunk)
        part.replace(dest)
    finally:
        resp.close()
        part.unlink(missing_ok=True)


# ── Orchestration ───────────────────────────────────────────

def _fmt_duration(sec: int) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _write_contents(course_dir: Path, course: dict, chapters: list[Chapter], langs: list[str]):
    lines = [f"# {course['title']}", ""]
    for ch in chapters:
        lines.append(f"## {ch.index}. {ch.title}" if ch.index else f"## {t('md_no_section')}")
        for lec in ch.lectures:
            tags = []
            for lang in langs:
                cap = pick_caption(lec.captions, lang)
                tags.append(f"{lang}{' (auto)' if cap and is_auto_caption(cap) else ''}" if cap else f"~~{lang}~~")
            lines.append(f"- {lec.number} {lec.title} [{_fmt_duration(lec.duration)}] — {', '.join(tags)}")
        lines.append("")
    (course_dir / "CONTENTS.md").write_text("\n".join(lines), encoding="utf-8")


def _write_combined(course_dir: Path, course: dict, chapters: list[Chapter], lang: str) -> int:
    """Gộp transcript cả khoá thành 1 file markdown (tiện đưa cho LLM). Trả số bài có nội dung."""
    out, count = [f"# {course['title']} — transcript [{lang}]", ""], 0
    for ch in chapters:
        section = []
        for lec in ch.lectures:
            txt = course_dir / lang / f"{lec.stem}.txt"
            if txt.exists():
                section += [f"### {lec.number} {lec.title}", "", txt.read_text(encoding="utf-8").strip(), ""]
                count += 1
        if section:
            out += [f"## {ch.index}. {ch.title}" if ch.index else f"## {t('md_no_section')}", ""] + section
    path = course_dir / f"transcript.{lang}.md"
    if count:
        path.write_text("\n".join(out), encoding="utf-8")
    elif path.exists():
        path.unlink()
    return count


def _items(value) -> list[str]:
    """what_you_will_learn_data / requirements_data là {"items": [...]}, các field khác là list thẳng."""
    if isinstance(value, dict):
        value = value.get("items")
    return [str(x).strip() for x in (value or []) if str(x).strip()]


def write_overview(course_dir: Path, host: str, details: dict):
    """OVERVIEW.md (theo ngôn ngữ giao diện hiện tại) + overview.json (raw). Cũng được gọi lại khi
    đổi ngôn ngữ giao diện — dựng lại từ overview.json, không cần gọi Udemy."""
    d = details
    lines = [f"# {d.get('title') or ''}".rstrip()]
    if d.get("headline"):
        lines += ["", f"> {d['headline']}"]

    facts = []
    instructors = [i.get("display_name") or i.get("title") or "" for i in d.get("visible_instructors") or []]
    jobs = [i.get("job_title") for i in d.get("visible_instructors") or []]
    if any(instructors):
        facts.append((t("ov_instructors"), ", ".join(f"{n} ({j})" if j else n for n, j in zip(instructors, jobs) if n)))
    cats = [c.get("title") for c in (d.get("primary_category"), d.get("primary_subcategory")) if isinstance(c, dict) and c.get("title")]
    if cats:
        facts.append((t("ov_category"), " › ".join(cats)))
    if d.get("instructional_level_simple"):
        facts.append((t("ov_level"), d["instructional_level_simple"]))
    if isinstance(d.get("locale"), dict) and d["locale"].get("title"):
        facts.append((t("ov_language"), d["locale"]["title"]))
    lectures = t("ov_lectures", n=d["num_lectures"]) if d.get("num_lectures") else None
    length = " · ".join(x for x in (d.get("content_info"), lectures) if x)
    if length:
        facts.append((t("ov_length"), length))
    if isinstance(d.get("rating"), (int, float)):
        rating = f"{d['rating']:.1f}/5"
        if d.get("num_reviews"):
            rating += " (" + t("ov_reviews", n=f"{d['num_reviews']:,}") + ")"
        if d.get("num_subscribers"):
            rating += " · " + t("ov_students", n=f"{d['num_subscribers']:,}")
        facts.append((t("ov_rating"), rating))
    if d.get("caption_languages"):
        facts.append((t("ov_captions"), ", ".join(d["caption_languages"])))
    if d.get("last_update_date"):
        facts.append((t("ov_updated"), d["last_update_date"]))
    if d.get("url"):
        url = d["url"] if d["url"].startswith("http") else f"https://{host}{d['url']}"
        facts.append((t("ov_link"), url))
    if facts:
        lines += [""] + [f"- **{k}:** {v}" for k, v in facts]

    sections = [
        (t("ov_learn"), _items(d.get("what_you_will_learn_data")) or _items(d.get("objectives"))),
        (t("ov_requirements"), _items(d.get("requirements_data")) or _items(d.get("prerequisites"))),
    ]
    for heading, items in sections:
        if items:
            lines += ["", f"## {heading}", ""] + [f"- {x}" for x in items]
    description = html_to_markdown(d.get("description") or "")
    if description:
        lines += ["", f"## {t('ov_description')}", "", description]
    audiences = _items(d.get("target_audiences"))
    if audiences:
        lines += ["", f"## {t('ov_audience')}", ""] + [f"- {x}" for x in audiences]

    (course_dir / "OVERVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (course_dir / "overview.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_resource_index(res_dir: Path, course: dict, items: list):
    lines, last_chapter, last_lecture = [f"# {t('md_resources_title', title=course['title'])}"], None, None
    for res, path in items:
        if res.chapter_index != last_chapter:
            lines += ["", f"## {res.chapter_index}. {res.chapter_title}" if res.chapter_index else f"## {t('md_no_section')}", ""]
            last_chapter, last_lecture = res.chapter_index, None
        if res.lecture_id != last_lecture:
            lines.append(f"- **{res.lecture_title}**")
            last_lecture = res.lecture_id
        if res.is_link:
            url = res.asset.get("external_url")
            lines.append(f"  - 🔗 [{res.asset.get('title') or url}]({url})")
        else:
            rel = path.relative_to(res_dir).as_posix()
            lines.append(f"  - [{path.name}](<{rel}>)" + ("" if path.exists() else f" — *{t('md_not_downloaded')}*"))
    (res_dir / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_outline(items: list[dict], chapters: list[Chapter], langs: list[str], course_dir: Path,
                  index_items: list) -> list[dict]:
    """Toàn bộ bài theo thứ tự hiển thị (cả bài article — để trang HTML hiện file đính kèm của chúng),
    lưu vào course.json để render.py dựng lại HTML mà không cần gọi Udemy."""
    videos = {lec.id: lec for ch in chapters for lec in ch.lectures}
    res_by_lecture: dict[int, list] = {}
    for res, path in index_items:
        if res.is_link:
            entry = {"kind": "link", "name": res.asset.get("title") or res.asset.get("external_url"),
                     "url": res.asset.get("external_url")}
        else:
            entry = {"kind": "file", "name": path.name, "path": path.relative_to(course_dir).as_posix(),
                     "ok": path.exists()}
        res_by_lecture.setdefault(res.lecture_id, []).append(entry)

    outline = [{"index": 0, "title": "", "lectures": []}]
    for it in _ordered(items):
        cls = it.get("_class")
        if cls == "chapter":
            outline.append({"index": len(outline), "title": it.get("title") or "", "lectures": []})
        elif cls == "lecture":
            lec = videos.get(it["id"])
            entry = {"id": it["id"], "title": it.get("title") or f"Lecture {it['id']}",
                     "kind": "video" if lec else str((it.get("asset") or {}).get("asset_type") or "other").lower(),
                     "resources": res_by_lecture.get(it["id"], [])}
            if lec:
                captions = {}
                for lang in langs:
                    cap = pick_caption(lec.captions, lang)
                    captions[lang] = None if not cap else ("auto" if is_auto_caption(cap) else "manual")
                entry.update(number=lec.number, stem=lec.stem, duration=lec.duration, captions=captions,
                             transcripts={lang: (course_dir / lang / f"{lec.stem}.txt").exists() for lang in langs})
            outline[-1]["lectures"].append(entry)
    if not outline[0]["lectures"]:
        outline.pop(0)
    return outline


def download_course(url: str, token: str, out_root: Path, langs: list[str], force: bool = False,
                    workers: int = 4, log=print, progress=lambda done, total: None, resources: bool = True,
                    client_factory=UdemyClient, vtt_fetcher=fetch_vtt, file_fetcher=fetch_file) -> dict:
    host, slug = parse_course_url(url)
    client = client_factory(host, token)
    try:
        client.me()  # Udemy trả 403 (không phải 401) khi token sai — kiểm tra trước cho thông báo rõ ràng
    except AuthError as e:
        raise AuthError(t("invalid_token", err=e), e.status)
    log(t("log_finding", slug=slug, host=host))
    course = client.resolve_course(slug)
    log(t("log_course", id=course["id"], title=course["title"]))

    items = client.curriculum(course["id"])
    chapters = build_structure(items)
    lectures = [lec for ch in chapters for lec in ch.lectures]
    log(t("log_structure", chapters=len(chapters), lectures=len(lectures)))

    course_dir = out_root / sanitize_filename(slug)
    course_dir.mkdir(parents=True, exist_ok=True)
    _write_contents(course_dir, course, chapters, langs)

    # Tổng quan khoá luôn lấy lại (giảng viên có thể sửa mô tả); lỗi thì chỉ cảnh báo, không dừng job
    headline = None
    try:
        details = client.course_details(course["id"])
        write_overview(course_dir, host, details)
        headline = details.get("headline")
        log(t("log_overview_saved"))
    except UdemyError as e:
        log(t("log_overview_failed", err=e))

    stats = {lang: {"available": 0, "downloaded": 0, "skipped": 0, "missing": 0, "failed": 0, "auto": 0} for lang in langs}
    tasks = []
    for lang in langs:
        (course_dir / lang).mkdir(exist_ok=True)
        for lec in lectures:
            cap = pick_caption(lec.captions, lang)
            if not cap:
                stats[lang]["missing"] += 1
                continue
            stats[lang]["available"] += 1
            stats[lang]["auto"] += is_auto_caption(cap)
            srt, txt = course_dir / lang / f"{lec.stem}.srt", course_dir / lang / f"{lec.stem}.txt"
            if not force and srt.exists() and txt.exists():
                stats[lang]["skipped"] += 1
                continue
            tasks.append((lang, lec, cap, srt, txt))

    for lang in langs:
        s = stats[lang]
        log(t("log_captions", lang=lang, available=s["available"], total=len(lectures), auto=s["auto"], skipped=s["skipped"]))

    def write_transcript(cap, srt, txt):
        cues = parse_vtt(vtt_fetcher(cap["url"]))
        srt.write_text(cues_to_srt(cues), encoding="utf-8")
        txt.write_text(cues_to_text(cues), encoding="utf-8")

    # (bộ đếm stats, nhãn cho log, hàm chạy trong thread pool)
    work = [(stats[lang], f"[{lang}] {lec.number} {lec.title}", lambda c=cap, s=srt, t=txt: write_transcript(c, s, t))
            for lang, lec, cap, srt, txt in tasks]

    res_stats, res_dir, index_items = None, course_dir / "resources", []
    if resources:
        res_stats = {"files": 0, "downloaded": 0, "skipped": 0, "failed": 0, "links": 0}
        used = {}
        for res in collect_resources(items):
            if res.is_link:
                res_stats["links"] += 1
                index_items.append((res, None))
                continue
            path = res_dir / res.folder / res.filename
            if used.setdefault(path, res.asset["id"]) != res.asset["id"]:  # trùng tên trong cùng chương
                path = path.with_name(f"{path.stem} ({res.asset['id']}){path.suffix}")
                used[path] = res.asset["id"]
            index_items.append((res, path))
            res_stats["files"] += 1
            if not force and path.exists() and path.stat().st_size > 0:
                res_stats["skipped"] += 1
                continue
            try:
                # client không thread-safe → lấy link tuần tự ở đây, chỉ phần tải file chạy song song
                file_url = client.asset_download_url(course["id"], res.lecture_id, res.asset["id"])
                path.parent.mkdir(parents=True, exist_ok=True)
            except (UdemyError, OSError) as e:  # OSError: vd đường dẫn quá dài trên Windows
                res_stats["failed"] += 1
                log(t("log_file_error", name=path.name, err=e))
                continue
            work.append((res_stats, f"[file] {path.name}", lambda u=file_url, p=path: file_fetcher(u, p)))
        log(t("log_files", files=res_stats["files"], links=res_stats["links"], skipped=res_stats["skipped"]))

    done = 0
    progress(done, len(work))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [(stat, label, pool.submit(fn)) for stat, label, fn in work]
        for stat, label, fut in futures:
            try:
                fut.result()
                stat["downloaded"] += 1
            except Exception as e:  # 1 bài/file lỗi không được làm hỏng cả khoá
                stat["failed"] += 1
                log(t("log_task_error", label=label, err=e))
            done += 1
            progress(done, len(work))

    if index_items:
        res_dir.mkdir(exist_ok=True)
        _write_resource_index(res_dir, course, index_items)

    combined = {lang: _write_combined(course_dir, course, chapters, lang) for lang in langs}
    meta = {
        "id": course["id"],
        "title": course["title"],
        "headline": headline,
        "overview": (course_dir / "OVERVIEW.md").exists(),
        "slug": course_dir.name,
        "host": host,
        "url": f"https://{host}/course/{slug}/",
        "lecture_count": len(lectures),
        "chapter_count": len(chapters),
        "langs": langs,
        "stats": stats,
        "combined": combined,
        "resources": res_stats,
        "updated_at": int(time.time()),
        "outline": build_outline(items, chapters, langs, course_dir, index_items),
    }
    try:
        from render import render_course
        pages = render_course(course_dir, meta)
        meta["html"] = True
        log(t("log_html_done", pages=", ".join(pages)))
    except Exception as e:  # lỗi dựng HTML không được làm mất dữ liệu đã tải
        meta["html"] = (course_dir / "index.html").exists()
        log(t("log_html_failed", err=e))
    (course_dir / "course.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    for lang in langs:
        s = stats[lang]
        log(t("log_lang_done", lang=lang, downloaded=s["downloaded"], skipped=s["skipped"], failed=s["failed"], missing=s["missing"]))
    if res_stats:
        r = res_stats
        log(t("log_files_done", downloaded=r["downloaded"], skipped=r["skipped"], failed=r["failed"]))
    return meta
