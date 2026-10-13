# Udemy Transcript

Tải về máy **transcript**, **tổng quan khoá** và **file đính kèm** (pdf, docx…) của các khoá Udemy bạn đã mua, rồi đọc ngay trên trình duyệt — có mục lục, đổi qua lại tiếng Anh ⇄ tiếng Việt mà vẫn giữ đúng bài đang đọc.

Dán link khoá → bấm **Tải** → bấm **📖 Đọc trên trình duyệt**. Vậy thôi.

> ⚠️ Chỉ dùng cho khoá học **bạn đã sở hữu**, cho mục đích học tập cá nhân. Nội dung khoá học thuộc bản quyền của giảng viên/Udemy — đừng chia sẻ lại các file đã tải. Tự chịu trách nhiệm tuân thủ [Điều khoản sử dụng của Udemy](https://www.udemy.com/terms/) (và quy định của công ty nếu dùng Udemy Business).
>
> Dự án độc lập, **không liên kết, không được Udemy tài trợ hay xác nhận**. "Udemy" là thương hiệu của Udemy, Inc. App không tải video và không vượt qua DRM — chỉ lấy phụ đề và file đính kèm mà tài khoản của bạn vốn đã xem/tải được.

## Tính năng

- **Transcript từng bài** dạng `.txt` và `.srt` (có mốc thời gian), cộng **1 file gộp cả khoá** cho mỗi ngôn ngữ — tiện đưa cho ChatGPT/Claude tóm tắt hay hỏi đáp.
- **Chọn ngôn ngữ** (mặc định tiếng Anh + tiếng Việt). Ưu tiên phụ đề gốc do giảng viên upload; bản dịch máy của Udemy được đánh dấu rõ.
- **File đính kèm** của mọi bài, kể cả bài đọc (Article), xếp theo chương.
- **Tổng quan khoá**: giới thiệu, "Bạn sẽ học được gì", yêu cầu, đối tượng, giảng viên, đánh giá…
- **Trang đọc HTML**: trang chủ khoá (mục lục + link tới từng bài và file đính kèm), trang tổng quan, trang transcript có mục lục bám theo vị trí đang đọc. Link tương đối nên mở thẳng từ ổ đĩa hay file zip cũng được.
- **Chạy lại không tải trùng**: bài/file đã có được bỏ qua, chỉ tải phần mới.
- Hỗ trợ **Udemy Business** (tài khoản công ty, `<tên-công-ty>.udemy.com`).
- Nhanh: tải thẳng file phụ đề qua API — một khoá ~60 bài mất vài giây, không cần mở trình duyệt tự động.

## Cài đặt & chạy

Chọn 1 trong 3 cách.

### 1. Windows — bản portable (không cần cài gì)

Tải file `UdemyTranscript-<phiên bản>-portable.zip`, giải nén vào thư mục **có đường dẫn ngắn** (vd `D:\UdemyTranscript`), double-click **`UdemyTranscript.vbs`** → trình duyệt tự mở `http://localhost:8097`. Tắt bằng nút **⏻ Tắt ứng dụng** trên trang. Hướng dẫn chi tiết nằm trong `README_USER.txt` của gói.

Tự build gói (trên Windows, cần Python 3.12 và internet):

```bash
python windows-portable/build_portable.py v1.0
# → windows-portable/dist/UdemyTranscript-v1.0-portable.zip (~16 MB)
```

### 2. Docker

```bash
docker build -t udemy-transcript .
docker run -d --name udemy-transcript --restart unless-stopped \
  -p 127.0.0.1:8096:8096 -v "$(pwd)/data:/app/data" udemy-transcript
```

Mở http://localhost:8096. Dữ liệu nằm trong `./data` trên máy.

### 3. Python

```bash
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8096
```

## Đăng nhập Udemy

App dùng cookie `access_token` của chính trình duyệt bạn (không cần mật khẩu):

1. Đăng nhập udemy.com như bình thường.
2. F12 → tab **Application** (Chrome/Edge) hoặc **Storage** (Firefox) → **Cookies** → `https://www.udemy.com` (tài khoản công ty: `https://<tên-công-ty>.udemy.com`).
3. Copy giá trị dòng `access_token`, dán vào ô **Đăng nhập Udemy** trên app → **Lưu**.

Token hết hạn thì làm lại. Nếu bị Cloudflare chặn, dán nguyên chuỗi header `Cookie` (tab Network) thay vì chỉ `access_token`. Có thể đặt sẵn qua biến môi trường `UDEMY_ACCESS_TOKEN` thay vì dán trên web.

## Dữ liệu tải về

```
data/
  token.txt                         ← token đăng nhập — đừng chia sẻ
  courses/<tên-khoá>/
    index.html                      ← mở file này để đọc
    overview.html, transcript.en.html, transcript.vi.html
    OVERVIEW.md                     tổng quan khoá
    transcript.en.md, transcript.vi.md   transcript gộp cả khoá
    CONTENTS.md                     mục lục, bài nào có phụ đề ngôn ngữ nào
    en/01.01 <tên bài>.txt | .srt
    vi/...
    resources/<chương>/<file đính kèm>
    resources/INDEX.md
```

## Dòng lệnh

```bash
python cli.py "https://www.udemy.com/course/<tên-khoá>/" [--langs en,vi] [--force] [--no-resources]
python render.py --all        # dựng lại các trang HTML từ dữ liệu đã tải, không gọi Udemy
```

`--force` tải lại cả những bài đã có; `--no-resources` bỏ qua file đính kèm.

## Cấu hình

| Biến môi trường | Mặc định | |
|---|---|---|
| `UDEMY_ACCESS_TOKEN` | — | Token đăng nhập (token dán trên web được ưu tiên hơn) |
| `TRANSCRIPT_LANGS` | `en,vi` | Ngôn ngữ mặc định khi tải |
| `TRANSCRIPT_WORKERS` | `4` | Số file tải song song |
| `DATA_DIR` | `./data` | Thư mục lưu dữ liệu |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host được phép truy cập web UI |

## Bảo mật

App được thiết kế để chạy **trên chính máy của bạn**:

- Bản Docker chỉ lắng nghe `127.0.0.1`; app từ chối request có Host lạ (chống DNS rebinding), và các lệnh không có body (tắt app, mở thư mục) đòi header riêng nên trang web khác không gửi hộ được.
- Token không bao giờ được trả ra qua API; chỉ được gửi tới `udemy.com` / `*.udemy.com`.
- Nội dung lấy từ Udemy được escape khi dựng HTML; các trang đọc chặn mọi kết nối mạng từ script (CSP `connect-src 'none'`).

**Đừng** mở app ra mạng ngoài (vd đổi `-p 0.0.0.0:...`) — app không có đăng nhập riêng, ai vào được trang là dùng được token của bạn.

## Phát triển

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Chi tiết kiến trúc, các endpoint Udemy đã kiểm chứng và lịch sử sửa lỗi nằm trong [`CLAUDE.md`](CLAUDE.md).

## Hạn chế

- Chỉ lấy transcript của bài **video**; nội dung chữ của bài đọc, quiz, bài tập code chưa được lưu (file đính kèm của chúng thì có).
- Phụ đề tiếng Việt trên Udemy phần lớn là **dịch máy** — chất lượng tham khảo.
- Bản portable chưa có tự động cập nhật: giải nén bản mới rồi copy thư mục `data\` cũ sang.

## License

[MIT](LICENSE) © 2026 madu — áp dụng cho **mã nguồn** của repo này, không áp dụng cho nội dung khoá học tải về bằng app.

## Ghi nhận

Ý tưởng ban đầu từ [TOA-Anakin/udemy-transcript-downloader](https://github.com/TOA-Anakin/udemy-transcript-downloader) (Node.js + Puppeteer). Bản này viết lại từ đầu bằng Python: tải phụ đề trực tiếp qua API thay vì điều khiển trình duyệt, và bổ sung file đính kèm, tổng quan khoá, trang đọc HTML, bản Windows portable.
