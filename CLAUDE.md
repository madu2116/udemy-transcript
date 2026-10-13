# udemy-transcript

Dán URL 1 khoá Udemy đã mua → tải transcript (tiếng Anh + tiếng Việt nếu có) thành `.txt` + `.srt` từng bài và 1 file markdown gộp cả khoá (tiện đưa cho LLM tóm tắt/học).

## Stack

- **Backend**: FastAPI + uvicorn (port 8096), `main.py` — job queue trong RAM, 1 worker thread chạy tuần tự từng khoá. Không DB.
- **Lõi**: `udemy.py` — client API Udemy (`curl_cffi`, giả TLS fingerprint Chrome để qua Cloudflare), parse VTT → SRT/text, gom curriculum thành chương/bài, `download_course()` điều phối.
- **CLI**: `cli.py` — cùng lõi, không cần web UI.
- **Trang đọc HTML**: `render.py` — dựng `index.html`/`overview.html`/`transcript.<lang>.html` từ dữ liệu đã có trên đĩa (không gọi Udemy). `markdown-it-py` chỉ dùng cho `OVERVIEW.md`.
- **Frontend**: `static/index.html` — HTML/CSS/JS thuần, bake vào image (sửa xong phải rebuild, hoặc `docker cp` như story-writer).
- **Triển khai**: service `udemy-transcript` trong `docker-compose.yml` gốc, `restart: unless-stopped`, bind **`127.0.0.1:8096`** (không mở ra LAN vì app giữ token đăng nhập Udemy). Card trong `docs/dashboard.html`.

```bash
docker compose build udemy-transcript && docker compose up -d udemy-transcript
docker compose logs -f udemy-transcript
docker compose exec udemy-transcript python cli.py "https://www.udemy.com/course/<slug>/" --langs en,vi [--force]

# Dựng lại HTML sau khi sửa render.py (không tải lại gì; cần course.json có outline)
docker compose exec udemy-transcript python render.py --all

# Test (chạy trên host, không cần curl_cffi — import lazy)
cd projects/udemy-transcript && python -m pytest tests -q
```

## Khác repo gốc thế nào

Dựa trên ý tưởng của [TOA-Anakin/udemy-transcript-downloader](https://github.com/TOA-Anakin/udemy-transcript-downloader) (Node + Puppeteer), viết lại vì:

| Repo gốc | Ở đây |
|---|---|
| Mở từng bài trong Chrome headless, bấm nút "Transcript", đọc `textContent` của panel | Tải thẳng file VTT mà API curriculum đã trả URL sẵn — transcript panel của Udemy chính là phụ đề đó. Không cần trình duyệt |
| Login email + OTP mỗi lần chạy, không lưu phiên | Cookie `access_token` (dán 1 lần) |
| `page_size=200`, không phân trang → khoá >200 item bị cụt | Theo `next` tới hết (giới hạn 100 trang) |
| Mọi khoá ghi chung `output/` (đè `CONTENTS.txt`) | Mỗi khoá 1 thư mục, chạy lại thì bỏ qua bài đã có |
| Chỉ text, không phân biệt ngôn ngữ | Chọn theo ngôn ngữ, ưu tiên phụ đề giảng viên upload hơn bản `[Auto]` |

## Đăng nhập

- Token lấy từ: `data/token.txt` (dán qua web UI) **ưu tiên hơn** `UDEMY_ACCESS_TOKEN` trong `.env` — để khi token hết hạn chỉ cần dán lại trên web, không phải force-recreate container. Nút "Xoá" trên UI xoá file → quay về dùng `.env`.
- Ô token nhận cả token trần lẫn nguyên chuỗi `Cookie:` header copy từ DevTools (`parse_token`) — dùng cách sau nếu bị Cloudflare chặn (kèm `cf_clearance`).
- Gửi token qua cả `Authorization: Bearer`, `X-Udemy-Authorization` và cookie. `_get()` từ chối gửi tới host khác host của khoá (kể cả URL `next` của phân trang); `parse_course_url` chỉ nhận `udemy.com`/`*.udemy.com` (Udemy Business dùng subdomain riêng).
- URL phụ đề là link CDN đã ký (`vtt-c.udemycdn.com`) → `fetch_vtt` tải không kèm token.
- API không trả token ra ngoài (`GET /api/token` chỉ trả `source`/`valid`/`user`) — có test đảm bảo.
- **Quan sát thực tế (2026-10-13)**: qua `curl_cffi` impersonate chrome, `api-2.0` trả JSON bình thường, không gặp Cloudflare challenge. Không có/sai token thì `/users/me/` trả **403** (không phải 401) → `download_course` gọi `me()` trước tiên để báo "token không hợp lệ" ngay, thay vì đi dò khoá rồi lỗi mơ hồ.
- Nút "Kiểm tra" token luôn gọi `www.udemy.com`; token Business vẫn qua được bước này (đã thấy 2026-10-13), còn khi tải thì `me()` gọi đúng subdomain của khoá.

## Luồng `download_course`

1. `parse_course_url` → `(host, slug)`; `me()` kiểm tra token.
2. `resolve_course(slug)` → course id. Thử lần lượt, nguồn nào lỗi (trừ 401) thì sang nguồn sau: `api-2.0/courses/<slug>/` (API nhận thẳng slug — nhanh nhất, chạy cả Business) → quét toàn bộ `users/me/subscribed-courses` → `users/me/subscription-course-enrollments?search=` (Personal Plan) → `data-clp-course-id` trên trang khoá (cách của repo gốc).
3. `curriculum(id)` → `subscriber-curriculum-items` với `fields[lecture]=...,supplementary_assets` và `fields[asset]=asset_type,time_estimation,captions,title,filename,external_url` (`fields[asset]` áp cho cả asset chính lẫn file đính kèm).
4. `build_structure` — sort `sort_order` **giảm dần** (Udemy đánh ngược, theo repo gốc; nếu thiếu `sort_order` ở bất kỳ item nào thì giữ thứ tự API). Chỉ giữ lecture có `asset_type` chứa `video`. Bài nằm trước chương đầu tiên → chương 0.
5. Với mỗi ngôn ngữ: `pick_caption` khớp prefix `locale_id` (`en_US`, `en_GB` → `en`), manual trước auto. Tải song song (`TRANSCRIPT_WORKERS`, mặc định 4); 1 bài lỗi chỉ ghi log + đếm `failed`, không dừng cả khoá.
6. Tài nguyên đính kèm (`resources=True`, mặc định; UI checkbox, CLI `--no-resources`): `collect_resources` lấy `supplementary_assets` của **mọi** lecture — kể cả bài Article (bị `build_structure` bỏ qua vì không có phụ đề; khoá thật có 23/34 file nằm ở bài Article). Link tải lấy **tuần tự** trong main thread (`asset_download_url` → `users/me/subscribed-courses/<cid>/lectures/<lid>/supplementary-assets/<aid>/?fields[asset]=download_urls`, vì session curl_cffi không thread-safe), chỉ phần tải file (`fetch_file`, stream ra `.part` rồi rename) chạy chung thread pool với phụ đề. Link CDN `att-c.udemycdn.com` đã ký, tải không cần token. `/api-2.0/assets/<id>/` trả 403 với file đính kèm — đừng dùng. `ExternalLink` không tải, chỉ ghi vào INDEX. Trùng tên file trong cùng chương → thêm ` (<asset id>)`. Đã có file (size > 0) thì bỏ qua trừ khi `force`.
7. Tổng quan khoá: `course_details(id)` → `api-2.0/courses/<id>/?fields[course]=COURSE_DETAIL_FIELDS` (headline, description HTML, `what_you_will_learn_data`/`requirements_data` dạng `{"items": [...]}`, `target_audiences`, giảng viên, danh mục, rating...; `@all` trả 404 trên Business nên phải liệt kê field). Ghi `OVERVIEW.md` (description qua `html_to_markdown` — parser stdlib tự viết, heading trong mô tả hạ xuống từ cấp 3; `&nbsp;` thành dấu cách thường) + `overview.json` (raw). Luôn lấy lại mỗi lần chạy; lỗi chỉ log CẢNH BÁO và giữ file cũ, không dừng job.
8. Ghi `CONTENTS.md`, `resources/INDEX.md`, `transcript.<lang>.md` (gộp từ các `.txt` đã có, kể cả bài bỏ qua do đã tải trước đó; không có bài nào thì xoá file gộp cũ).
9. `build_outline` → `course.json["outline"]`: **mọi** lecture theo thứ tự hiển thị (video có `number/stem/duration/captions{lang: manual|auto|None}/transcripts{lang: bool}`; article/khác chỉ có `kind`), kèm `resources` từng bài (`file` có `path` tương đối tính từ thư mục khoá + `ok`, `link` có `url`). Rồi `render.render_course(course_dir, meta)` — lỗi chỉ log CẢNH BÁO, `meta["html"]` = có `index.html` hay không. Cuối cùng mới ghi `course.json`.

## Trang đọc HTML (`render.py`)

| File `.md` | HTML | Ghi chú |
|---|---|---|
| `transcript.<lang>.md` | `transcript.<lang>.html` | Dựng từ outline + `.txt` (không parse lại md) để có anchor ổn định `l-<chương>-<bài>` (vd `l-03-02`), mục lục sticky bên trái (gập lại thành khối trên cùng khi ≤900px), JS đánh dấu bài đang đọc + `history.replaceState` hash, nút đổi ngôn ngữ `data-keep-hash` mang theo hash → sang bản kia đúng bài. Ngôn ngữ toàn `auto` có banner "dịch máy". |
| `CONTENTS.md` + `resources/INDEX.md` | `index.html` (gộp) | Trang chủ khoá: headline + facts từ `overview.json`, nút tới overview/transcript, mỗi bài có chip EN/VI link thẳng tới anchor (viền cam = dịch máy, nét đứt = không có) + link file đính kèm. Bài article hiện với nhãn "Bài đọc". |
| `OVERVIEW.md` | `overview.html` | markdown-it `commonmark`, `html=False`. |

Không convert: `.txt`/`.srt` từng bài (đã nằm trong trang transcript; `.srt` cho video player), `course.json`/`overview.json`. Các `.md` vẫn giữ để đưa cho LLM.

**An toàn**: mọi chữ từ Udemy qua `html.escape`; markdown-it `html=False` hiện HTML thô thành chữ và tự chặn link `javascript:`/`data:`. Route `/view` thêm CSP `connect-src 'none'` (+ `default-src 'none'`, `form-action 'none'`) cho file `.html` → kể cả lọt script cũng không fetch được `/api/token` hay `/api/*`. Link trong trang đều **tương đối** (test `test_html_links_are_relative_and_resolve` kiểm mọi href trỏ tới file có thật) → mở qua app, mở thẳng từ đĩa hay giải nén zip đều chạy.

Khoá tải bằng bản trước khi có outline: `render_course` báo lỗi "chưa có outline" → bấm Cập nhật trên UI một lần (transcript/file đã có được bỏ qua, chỉ mất vài giây).

`cues_to_text`: bỏ cue trùng liền kề (auto-caption hay lặp), ngắt đoạn chỉ khi câu kết thúc **và** (im lặng ≥2s hoặc đoạn ≥700 ký tự) — phụ đề Udemy thường liền mạch không có khoảng lặng.

## Data layout

```
data/
  token.txt                         # token dán qua web (gitignored cùng data/)
  courses/<slug>/
    course.json                     # meta + stats từng ngôn ngữ (UI đọc file này)
    index.html                      # trang chủ khoá để đọc trên trình duyệt (render.py)
    overview.html
    transcript.en.html | transcript.vi.html
    OVERVIEW.md                     # tổng quan: headline, giảng viên, bạn sẽ học được gì, yêu cầu, mô tả, đối tượng
    overview.json                   # raw response course_details
    CONTENTS.md                     # mục lục, đánh dấu bài có/không có phụ đề từng ngôn ngữ
    transcript.en.md                # gộp cả khoá
    transcript.vi.md
    en/01.02 <tên bài>.txt|.srt
    vi/...
    resources/
      INDEX.md                      # chương → bài → file / link ngoài (link tương đối tới file)
      03 <tên chương>/<tên file gốc>.pdf|.docx|...
```

## API

| Method | Path | |
|---|---|---|
| GET | `/api/token[?check=1]` | trạng thái token (không bao giờ trả token) |
| POST/DELETE | `/api/token` | lưu / xoá token trong `data/token.txt` |
| POST | `/api/jobs` | `{url, langs?, force?, resources?=true}` → job (mặc định `TRANSCRIPT_LANGS`) |
| GET | `/api/jobs`, `/api/jobs/{id}` | danh sách 20 job gần nhất / chi tiết kèm log |
| GET | `/api/courses` | các khoá đã tải (từ `course.json`) |
| GET | `/api/courses/{slug}/transcript/{lang}[?download=1]` | file gộp |
| GET | `/api/courses/{slug}/overview[?download=1]` | `OVERVIEW.md` |
| GET | `/api/courses/{slug}/zip` | zip cả thư mục khoá (transcript + tài nguyên) |

| GET | `/view/{slug}` → 307 `/view/{slug}/` | dấu `/` cuối để link tương đối trong trang đúng |
| GET | `/view/{slug}/{path}` | file tĩnh trong thư mục khoá (mặc định `index.html`); `.html` kèm CSP ở trên. Chỉ GET (HEAD trả 405 — `curl -I` không dùng được, trình duyệt không bị ảnh hưởng) |

`_course_dir` chặn path traversal (thư mục phải là con trực tiếp của `courses/` và có `course.json`); `/view` resolve thêm `path` và bắt buộc `is_relative_to(thư mục khoá)` → không đọc được `data/token.txt`.

## Bản Windows portable (`windows-portable/`)

ZIP chứa Python embeddable, double-click `.vbs`, không cần cài gì.

```bash
python windows-portable/build_portable.py v1.0 [--clean]   # chạy trên Windows → dist/UdemyTranscript-v1.0-portable.zip (~16 MB)
```

- **Build bằng Python, không PowerShell** (PowerShell.exe crash khi gọi từ Git Bash trên máy này). Phải chạy **trên Windows**: deps cài bằng `pip install --target runtime/Lib/site-packages --platform win_amd64 --python-version 312 --only-binary=:all:`, mà pip đánh giá environment marker theo máy đang chạy (vd `click` cần `colorama` khi win32). Bỏ extras (`uvicorn[standard]` → `uvicorn`). Runtime + deps được cache (hash requirements); `--clean` để làm lại từ đầu.
- **Layout gói**: `runtime/` (Python 3.12.10 embeddable, `._pth` bật `import site` + `Lib\site-packages`), `app/` (code + static), `data/` (tạo lúc chạy, **ngoài** `app/` → thay code bản mới không mất dữ liệu), `launcher.py`, `UdemyTranscript.vbs`, `start.bat` (debug, có console), `README_USER.txt`. `.bat`/`.vbs` ASCII + CRLF, README UTF-8 BOM + CRLF.
- **Zip không bao giờ chứa** `data/` (token!), `app.log`, `__pycache__`, `*.part` — `make_zip` assert sau khi đóng gói.
- **launcher.py**: pythonw → redirect stdout/stderr ra `app.log` UTF-8 (pythonw trên máy thật có stdout cp1252, không phải None — print tiếng Việt sẽ crash im lặng). Cổng **8097–8106** (tránh bản Docker 8096). Chỉ coi là phiên đang chạy khi `/api/app-info` trả `app=udemy-transcript`, `portable=true` **và đúng `data_dir`** — bản Docker hay bản giải nén ở thư mục khác không bị nhận nhầm. Lỗi khởi động → MessageBox + traceback trong app.log. `NO_BROWSER=1` = chế độ test tự động (không mở browser, không hiện dialog).
- **Server ở chế độ portable** (`PORTABLE_MODE=true`): `POST /api/shutdown` (Docker trả 403), `POST /api/open-folder[?slug=]` (Explorer, chỉ Windows), UI hiện nút "⏻ Tắt ứng dụng" / "📂 Thư mục dữ liệu" / "📂 Mở thư mục" từng khoá.
- **Bảo vệ (áp cho cả Docker)**: `TrustedHostMiddleware` chỉ nhận Host `localhost`/`127.0.0.1` (`ALLOWED_HOSTS`, chặn DNS rebinding); POST không có body JSON (shutdown, open-folder) bắt header `X-Requested-With: udemy-transcript` → trang web lạ không gửi được bằng form ẩn (POST JSON vốn an toàn vì FastAPI chỉ parse body khi Content-Type là JSON). Test đặt `ALLOWED_HOSTS` gồm `testserver` trong conftest.
- **Đường dẫn dài (gặp thật khi test 2026-10-13)**: giải nén vào thư mục sâu + `data\courses\<slug>\resources\<chương>\<file>` vượt MAX_PATH 260 → `WinError 206`, và lỗi `mkdir` lúc đó làm **chết cả job** (transcript cũng không tải). Sửa: (1) `config.long_path` thêm tiền tố `\\?\` cho `DATA_DIR` trên Windows → mọi đường dẫn con kế thừa, Python ghi được (đã kiểm: 34 file ở đường dẫn tới 327 ký tự); `config.display_path` bỏ tiền tố khi hiện/gọi Explorer; (2) lỗi lấy link/tạo thư mục của 1 file đính kèm chỉ đếm `failed`; (3) tên file đính kèm tối đa 100 ký tự; (4) launcher cảnh báo **1 lần** khi thư mục cài > 40 ký tự — Word/Excel/Explorer vẫn không mở được file > 260 ký tự dù Python ghi được, nên khuyên chuyển sang `D:\UdemyTranscript`.
- **Chưa có auto-update**: nâng cấp = giải nén bản mới + copy `data\` cũ sang (README_USER ghi rõ).
- **Đã smoke-test thật trên Windows (2026-10-13)**: giải nén zip → `runtime\pythonw.exe launcher.py` → app-info/Host/header guard đúng, lần chạy thứ 2 chỉ mở browser, tải trọn khoá Business (58+58 transcript, 34 file, 4 trang HTML), shutdown thoát hẳn process. Chưa thử double-click `.vbs` (cùng lệnh, nhưng mở browser/dialog thật) và chưa thử trên máy khác không có Python.

## Fix history

- **2026-10-13 — Udemy Business (`<công-ty>.udemy.com`) lỗi "HTTP 500 subscribed-courses"**: `subscribed-courses?search=<slug>` trả 500 trên Business (không search thì 200), mà `resolve_course` chỉ bỏ qua 403/404 nên job chết. Sửa: thêm bước gọi thẳng `courses/<slug>/` lên đầu, bỏ `search` khỏi subscribed-courses, mọi lỗi trừ 401 đều chuyển sang nguồn kế tiếp. Trang khoá Business cũng không có `data-clp-course-id`.

## Đã xác minh với tài khoản thật (2026-10-13, Udemy Business)

- Khoá 58 bài video / 17 chương tải xong ~8 giây, đúng thứ tự (sort_order giảm dần đúng).
- Field caption thật: `_class, asset_id, created, file_name, id, locale_id, source, status, title, url, video_label`. `source` là `manual`/`auto` đáng tin; `title` là **tên file** (vd `xxx.autogenerated.vtt`, kể cả với bản `manual`) — không dùng `title` để suy ra auto.
- Tài nguyên: 34 file (`.docx`/`.pdf`, toàn `asset_type=File`) trên 18 bài, tải ~5 giây, file mở được. Key thật của supplementary asset: `_class, asset_type, external_url, filename, id, time_estimation, title`; `title` = tên file gốc (có `_`), `filename` = bản Udemy đổi `_`→`-` → `Resource.filename` ưu tiên `title`.
- Phụ đề `vi` trên khoá đó đều là `auto` (dịch máy); `en_US` là `manual`. Có cả `es_LA`, `ko_KR`, `pl_PL`, ...

## Hạn chế

- Khoá không có phụ đề tiếng Việt thì chỉ có `en`; `vi` mà Udemy có thường là bản dịch máy — UI hiện số bài auto.
- Job queue nằm trong RAM — restart container là mất lịch sử job (file đã tải vẫn còn).
- Transcript chỉ lấy lecture video; **nội dung** bài article/quiz/coding exercise không được lưu (file đính kèm của bài article thì có).
- Số thứ tự `01.02` của transcript chỉ đếm bài video, nên lệch với số thứ tự Udemy hiển thị khi chương có xen bài article — giữ nguyên để không đổi tên file đã tải. Tài nguyên xếp theo thư mục chương thay vì số bài vì lý do này.
