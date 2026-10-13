"""Dựng trang HTML đọc trên trình duyệt từ dữ liệu đã tải của 1 khoá.

Nguồn: course.json (outline do download_course ghi), các .txt transcript, OVERVIEW.md, overview.json.
Không gọi Udemy — chạy lại bất cứ lúc nào (vd sau khi sửa giao diện):
    python render.py <thư mục khoá> [...]
    python render.py --all

Sinh ra (cạnh các file .md, link tương đối nên mở được qua app, mở thẳng từ đĩa hay từ zip):
    index.html               trang chủ khoá = CONTENTS.md + resources/INDEX.md gộp lại
    overview.html            OVERVIEW.md
    transcript.<lang>.html   transcript.<lang>.md, có mục lục + anchor từng bài + nút đổi ngôn ngữ giữ vị trí

Mọi chữ lấy từ Udemy đều được escape; markdown render với html=False nên HTML thô trong
nội dung chỉ hiện ra như chữ, link javascript:/data: bị markdown-it chặn.
"""
import html
import json
import sys
from pathlib import Path

from markdown_it import MarkdownIt

from i18n import get_lang, t

_md = MarkdownIt("commonmark", {"html": False})

LANG_NAMES = {"en": "English", "vi": "Tiếng Việt", "ja": "日本語", "ko": "한국어", "zh": "中文",
              "fr": "Français", "de": "Deutsch", "es": "Español", "pt": "Português", "it": "Italiano"}
KIND_LABELS = {"e-book": "E-book", "presentation": "Slide", "audio": "Audio", "externallink": "Link"}
KIND_KEYS = {"article": "kind_article", "file": "kind_file"}  # nhãn cần dịch


def kind_label(kind: str | None) -> str:
    if kind in KIND_KEYS:
        return t(KIND_KEYS[kind])
    return KIND_LABELS.get(kind, kind or "")


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


# Tên ngôn ngữ phụ đề theo ngôn ngữ GIAO DIỆN — dùng trong câu chữ ("Transcript Vietnamese").
# LANG_NAMES (tên gốc: "Tiếng Việt", "日本語") chỉ dùng cho nút chuyển ngôn ngữ, như checkbox trên web UI.
LANG_LABELS = {
    "en": {"en": "English", "vi": "Vietnamese", "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
           "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese", "it": "Italian"},
    "vi": {"en": "Tiếng Anh", "vi": "Tiếng Việt", "ja": "Tiếng Nhật", "ko": "Tiếng Hàn", "zh": "Tiếng Trung",
           "fr": "Tiếng Pháp", "de": "Tiếng Đức", "es": "Tiếng Tây Ban Nha", "pt": "Tiếng Bồ Đào Nha", "it": "Tiếng Ý"},
}


def lang_name(lang: str) -> str:
    """Tên gốc của ngôn ngữ (cho nút chuyển ngôn ngữ)."""
    return LANG_NAMES.get(lang, lang.upper())


def lang_label(lang: str) -> str:
    """Tên ngôn ngữ dịch theo giao diện (cho câu chữ, tiêu đề)."""
    return LANG_LABELS.get(get_lang(), LANG_LABELS["en"]).get(lang, lang.upper())


def anchor(number: str) -> str:
    return "l-" + number.replace(".", "-")


def fmt_duration(sec) -> str:
    m, s = divmod(int(sec or 0), 60)
    return f"{m}:{s:02d}"


def chapter_heading(ch: dict) -> str:
    return f"{ch['index']}. {ch['title']}" if ch["index"] else t("html_intro_section")


CSS = """
:root{--bg:#fbfbfa;--panel:#fff;--text:#1f2328;--muted:#6a7280;--border:#e4e6ea;--accent:#7c3aed;
--accent-soft:#f1eafe;--code:#f2f3f5;--warn:#9a5b00;--warn-soft:#fff4e0;--radius:10px}
@media (prefers-color-scheme:dark){:root{--bg:#131519;--panel:#1b1e24;--text:#e6e7ea;--muted:#9aa1ad;
--border:#2c3038;--accent:#b794f6;--accent-soft:#2a2340;--code:#23262d;--warn:#f0b45a;--warn-soft:#3a2d17}}
*{box-sizing:border-box}
html{scroll-padding-top:72px}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
.topbar{position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;flex-wrap:wrap;
padding:10px 20px;background:var(--panel);border-bottom:1px solid var(--border);font-size:14px}
.topbar .course{font-weight:600;flex:1 1 200px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.topbar a{text-decoration:none}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.seg a,.seg span{padding:3px 10px}
.seg .on{background:var(--accent);color:var(--panel);font-weight:600}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 80px}
.narrow{max-width:780px}
.layout{display:grid;grid-template-columns:280px minmax(0,1fr);gap:40px}
.toc{position:sticky;top:64px;align-self:start;max-height:calc(100vh - 80px);overflow:auto;font-size:14px;line-height:1.45}
.toc summary{cursor:pointer;font-weight:600;margin-bottom:8px}
.toc ol{list-style:none;margin:0;padding:0}
.toc .ch{margin:12px 0 4px;font-weight:600;color:var(--muted);font-size:13px}
.toc a{display:block;padding:3px 8px;border-radius:6px;color:var(--text);text-decoration:none}
.toc a:hover{background:var(--code)}
.toc a.active{background:var(--accent-soft);color:var(--accent);font-weight:600}
.toc .num,.num{color:var(--muted);font-variant-numeric:tabular-nums;margin-right:6px}
.content{max-width:72ch}
h1{font-size:30px;line-height:1.25;margin:0 0 8px}
h2{font-size:22px;margin:48px 0 8px;padding-top:8px;border-top:1px solid var(--border)}
.content section:first-of-type h2{border-top:0;margin-top:24px}
h3{font-size:18px;margin:32px 0 4px}
.meta{color:var(--muted);font-size:13px;margin-bottom:10px}
.headline{font-size:18px;color:var(--muted);margin:0 0 16px}
.badge{display:inline-block;font-size:12px;line-height:1.6;padding:0 8px;border-radius:999px;background:var(--code);color:var(--muted);margin-left:4px;vertical-align:1px}
.badge.auto{background:var(--warn-soft);color:var(--warn)}
.note{background:var(--warn-soft);color:var(--warn);border-radius:var(--radius);padding:10px 14px;font-size:14px;margin:12px 0}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}
.btn{display:inline-block;padding:8px 14px;border-radius:8px;border:1px solid var(--border);background:var(--panel);text-decoration:none;color:var(--text);font-weight:500}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--panel)}
.facts{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font-size:14px;margin:0;padding:0;list-style:none}
.outline{list-style:none;margin:0;padding:0}
.outline>li{display:grid;grid-template-columns:52px minmax(0,1fr) auto;gap:4px 12px;padding:10px 0;border-bottom:1px solid var(--border)}
.outline .t{font-weight:500}
.outline .side{color:var(--muted);font-size:13px;white-space:nowrap;text-align:right}
.outline .links{grid-column:2/4;display:flex;flex-wrap:wrap;gap:6px 14px;font-size:14px}
.chip{font-size:13px;padding:1px 9px;border-radius:999px;border:1px solid var(--border);text-decoration:none}
.chip.off{color:var(--muted);border-style:dashed}
.chip.auto{border-color:var(--warn);color:var(--warn)}
.res{font-size:14px}
.res .missing{color:var(--muted)}
.prose p{margin:0 0 1em}
.prose ul,.prose ol{padding-left:1.4em}
.prose blockquote{margin:0 0 16px;padding:4px 16px;border-left:3px solid var(--accent);color:var(--muted);font-size:18px}
.top{font-size:13px;color:var(--muted);text-decoration:none}
@media (max-width:900px){.layout{grid-template-columns:1fr;gap:0}
.toc{position:static;max-height:none;border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;margin-bottom:8px;background:var(--panel)}
h1{font-size:25px}.outline>li{grid-template-columns:44px minmax(0,1fr)}.outline .side{grid-column:2;text-align:left}}
@media print{.topbar,.toc{display:none}.layout{display:block}body{background:#fff;color:#000}}
"""

TRANSCRIPT_JS = """
<script>
(function(){
  var links={}; document.querySelectorAll('.toc a[href^="#"]').forEach(function(a){links[a.getAttribute('href').slice(1)]=a;});
  var current=null;
  function setActive(id){
    if(id===current) return; current=id;
    Object.keys(links).forEach(function(k){links[k].classList.toggle('active',k===id);});
    if(links[id]&&window.innerWidth>900) links[id].scrollIntoView({block:'nearest'});
    try{history.replaceState(null,'','#'+id);}catch(e){}
  }
  var arts=[].slice.call(document.querySelectorAll('article[id]'));
  function onScroll(){
    var best=null;
    for(var i=0;i<arts.length;i++){ if(arts[i].getBoundingClientRect().top<120) best=arts[i]; else break; }
    if(best) setActive(best.id);
  }
  var ticking=false;
  window.addEventListener('scroll',function(){ if(!ticking){ticking=true;requestAnimationFrame(function(){ticking=false;onScroll();});} },{passive:true});
  // Đổi ngôn ngữ: mang theo bài đang đọc
  document.querySelectorAll('a[data-keep-hash]').forEach(function(a){
    a.addEventListener('click',function(){ a.href=a.getAttribute('href').split('#')[0]+location.hash; });
  });
  if(window.innerWidth<=900){ var d=document.querySelector('.toc details'); if(d) d.removeAttribute('open'); }
  onScroll();
})();
</script>
"""


def page(title: str, body: str, script: str = "") -> str:
    return (
        f'<!doctype html>\n<html lang="{get_lang()}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n{body}\n{script}</body>\n</html>\n"
    )


def topbar(course_title: str, back: bool = True, extra: str = "") -> str:
    back_link = f'<a href="index.html">{esc(t("html_back"))}</a>' if back else ""
    return f'<header class="topbar">{back_link}<span class="course">{esc(course_title)}</span>{extra}</header>'


def resource_links(resources: list) -> str:
    out = []
    for r in resources:
        if r.get("kind") == "link":
            out.append(f'<a class="res" href="{esc(r.get("url"))}" target="_blank" rel="noopener noreferrer">🔗 {esc(r.get("name"))}</a>')
        elif r.get("ok"):
            out.append(f'<a class="res" href="{esc(r["path"])}">📎 {esc(r["name"])}</a>')
        else:
            out.append(f'<span class="res missing">📎 {esc(r["name"])} — {esc(t("html_not_downloaded"))}</span>')
    return "".join(out)


def _caption_langs(meta: dict) -> list[str]:
    """Ngôn ngữ có ít nhất 1 transcript, giữ thứ tự người dùng chọn."""
    return [lang for lang in meta.get("langs", []) if (meta.get("combined") or {}).get(lang)]


def _all_auto(meta: dict, lang: str) -> bool:
    s = (meta.get("stats") or {}).get(lang) or {}
    return bool(s.get("available")) and s.get("auto") == s.get("available")


# ── Trang chủ khoá ──────────────────────────────────────────

def render_index(meta: dict, details: dict | None, has_overview: bool) -> str:
    langs = _caption_langs(meta)
    outline = meta["outline"]
    n_files = sum(1 for ch in outline for lec in ch["lectures"] for r in lec.get("resources", []) if r.get("kind") == "file")

    facts = []
    if details:
        names = [i.get("display_name") for i in details.get("visible_instructors") or [] if i.get("display_name")]
        if names:
            facts.append("👤 " + ", ".join(names))
        if details.get("content_info"):
            facts.append("⏱ " + details["content_info"])
        if details.get("instructional_level_simple"):
            facts.append("📶 " + details["instructional_level_simple"])
        if details.get("last_update_date"):
            facts.append("🗓 " + t("html_updated", date=details["last_update_date"]))
    facts.append(t("html_counts", chapters=meta.get("chapter_count", len(outline)), lectures=meta.get("lecture_count", 0))
                 + (" · " + t("html_files", n=n_files) if n_files else ""))

    actions = []
    if has_overview:
        actions.append(f'<a class="btn" href="overview.html">{esc(t("html_overview_btn"))}</a>')
    for i, lang in enumerate(langs):
        label = f"Transcript {lang_label(lang)}" + (t("html_machine_suffix") if _all_auto(meta, lang) else "")
        actions.append(f'<a class="btn{" primary" if i == 0 else ""}" href="transcript.{esc(lang)}.html">{esc(label)}</a>')
    if meta.get("url"):
        actions.append(f'<a class="btn" href="{esc(meta["url"])}" target="_blank" rel="noopener noreferrer">{esc(t("html_open_udemy"))}</a>')

    sections = []
    for ch in outline:
        rows = []
        for lec in ch["lectures"]:
            if lec.get("kind") == "video":
                num = f'<span class="num">{esc(lec["number"])}</span>'
                side = fmt_duration(lec.get("duration"))
                chips = []
                for lang in meta.get("langs", []):
                    cap = (lec.get("captions") or {}).get(lang)
                    if (lec.get("transcripts") or {}).get(lang):
                        cls = "chip auto" if cap == "auto" else "chip"
                        title = esc(t("html_chip_auto") if cap == "auto" else t("html_chip_manual"))
                        chips.append(f'<a class="{cls}" title="{title}" href="transcript.{esc(lang)}.html#{anchor(lec["number"])}">{esc(lang.upper())}</a>')
                    else:
                        chips.append(f'<span class="chip off" title="{esc(t("html_chip_none"))}">{esc(lang.upper())}</span>')
                links = "".join(chips) + resource_links(lec.get("resources", []))
            else:
                num = '<span class="num">·</span>'
                side = kind_label(lec.get("kind"))
                links = resource_links(lec.get("resources", []))
            rows.append(
                f'<li>{num}<span class="t">{esc(lec["title"])}</span><span class="side">{esc(side)}</span>'
                + (f'<div class="links">{links}</div>' if links else "") + "</li>"
            )
        sections.append(f'<section id="c-{ch["index"]:02d}"><h2>{esc(chapter_heading(ch))}</h2><ol class="outline">{"".join(rows)}</ol></section>')

    headline = f'<p class="headline">{esc(details.get("headline"))}</p>' if details and details.get("headline") else ""
    body = (
        topbar(meta["title"], back=False)
        + f'<div class="wrap narrow"><h1>{esc(meta["title"])}</h1>{headline}'
        + '<ul class="facts">' + "".join(f"<li>{esc(f)}</li>" for f in facts) + "</ul>"
        + f'<div class="actions">{"".join(actions)}</div>'
        + f'<div class="content" style="max-width:none">{"".join(sections)}</div></div>'
    )
    return page(meta["title"], body)


# ── Tổng quan ───────────────────────────────────────────────

def render_overview(meta: dict, overview_md: str) -> str:
    body = (
        topbar(meta["title"])
        + f'<div class="wrap narrow"><div class="content prose">{_md.render(overview_md)}</div></div>'
    )
    return page(t("html_overview_title", title=meta["title"]), body)


# ── Transcript ──────────────────────────────────────────────

def _paragraphs(text: str) -> str:
    return "".join(f"<p>{esc(' '.join(p.split()))}</p>" for p in text.split("\n\n") if p.strip())


def render_transcript(meta: dict, course_dir: Path, lang: str) -> str | None:
    """None nếu ngôn ngữ này không có bài nào có transcript."""
    langs = _caption_langs(meta)
    toc, sections, count = [], [], 0
    for ch in meta["outline"]:
        toc_items, arts = [], []
        for lec in ch["lectures"]:
            if lec.get("kind") != "video":
                continue
            txt = course_dir / lang / f"{lec['stem']}.txt"
            if not txt.exists():
                continue
            count += 1
            aid = anchor(lec["number"])
            toc_items.append(f'<li><a href="#{aid}"><span class="num">{esc(lec["number"])}</span>{esc(lec["title"])}</a></li>')
            badge = (f'<span class="badge auto">{esc(t("html_badge_auto"))}</span>'
                     if (lec.get("captions") or {}).get(lang) == "auto" else "")
            res = resource_links(lec.get("resources", []))
            arts.append(
                f'<article id="{aid}"><h3><span class="num">{esc(lec["number"])}</span>{esc(lec["title"])}{badge}</h3>'
                f'<div class="meta">{fmt_duration(lec.get("duration"))}{" · " + res if res else ""}</div>'
                f'{_paragraphs(txt.read_text(encoding="utf-8"))}</article>'
            )
        if arts:
            heading = esc(chapter_heading(ch))
            toc.append(f'<li class="ch">{heading}</li>' + "".join(toc_items))
            sections.append(f'<section id="c-{ch["index"]:02d}"><h2>{heading}</h2>{"".join(arts)}</section>')
    if not count:
        return None

    switch = ""
    if len(langs) > 1:
        switch = '<span class="seg">' + "".join(
            f'<span class="on">{esc(lang_name(x))}</span>' if x == lang
            else f'<a href="transcript.{esc(x)}.html" data-keep-hash>{esc(lang_name(x))}</a>'
            for x in langs) + "</span>"
    # html_all_auto_note là chuỗi tin cậy của app (có <b>), không phải dữ liệu Udemy → không escape
    note = f'<div class="note">{t("html_all_auto_note")}</div>' if _all_auto(meta, lang) else ""
    body = (
        topbar(meta["title"], extra=switch)
        + '<div class="wrap"><div class="layout">'
        + f'<aside class="toc"><details open><summary>{esc(t("html_toc", n=count))}</summary><ol>{"".join(toc)}</ol></details></aside>'
        + f'<main class="content"><h1>Transcript · {esc(lang_label(lang))}</h1>{note}{"".join(sections)}'
        + f'<p><a class="top" href="#">{esc(t("html_back_to_top"))}</a></p></main></div></div>'
    )
    return page(f"Transcript {lang_label(lang)} — {meta['title']}", body, TRANSCRIPT_JS)


# ── Điều phối ───────────────────────────────────────────────

def render_course(course_dir: Path, meta: dict | None = None) -> list[str]:
    """Ghi index.html / overview.html / transcript.<lang>.html. Trả tên các file đã ghi."""
    course_dir = Path(course_dir)
    if meta is None:
        meta = json.loads((course_dir / "course.json").read_text(encoding="utf-8"))
    if not meta.get("outline"):
        raise ValueError(t("html_no_outline"))

    written = []
    overview_md = course_dir / "OVERVIEW.md"
    if overview_md.exists():
        (course_dir / "overview.html").write_text(render_overview(meta, overview_md.read_text(encoding="utf-8")), encoding="utf-8")
        written.append("overview.html")

    for lang in meta.get("langs", []):
        out = course_dir / f"transcript.{lang}.html"
        doc = render_transcript(meta, course_dir, lang)
        if doc:
            out.write_text(doc, encoding="utf-8")
            written.append(out.name)
        else:
            out.unlink(missing_ok=True)

    details = None
    if (course_dir / "overview.json").exists():
        try:
            details = json.loads((course_dir / "overview.json").read_text(encoding="utf-8"))
        except ValueError:
            details = None
    (course_dir / "index.html").write_text(render_index(meta, details, overview_md.exists()), encoding="utf-8")
    written.append("index.html")
    return written


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv == ["--all"]:
        import config
        dirs = sorted(p.parent for p in config.COURSES_DIR.glob("*/course.json"))
    else:
        dirs = [Path(a) for a in argv]
    failed = 0
    for d in dirs:
        try:
            print(f"{d.name}: {', '.join(render_course(d))}")
        except (OSError, ValueError) as e:
            failed += 1
            print(t("render_error", name=d.name, err=e), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
