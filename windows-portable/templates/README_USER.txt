UDEMY TRANSCRIPT — BẢN PORTABLE CHO WINDOWS
============================================

Tải transcript (phụ đề tiếng Anh/Việt), tổng quan khoá và file đính kèm
(pdf, docx...) của các khoá Udemy bạn đã mua, rồi đọc ngay trên trình duyệt.
Không cần cài Python hay Docker — mọi thứ nằm sẵn trong thư mục này.


1. CHẠY ỨNG DỤNG
----------------
- Giải nén file ZIP ra một thư mục (vd D:\UdemyTranscript). KHÔNG chạy thẳng
  trong file ZIP.
- Double-click  UdemyTranscript.vbs
  → trình duyệt tự mở trang http://localhost:8097 (nếu cổng bận sẽ dùng 8098, 8099...).
- Không có cửa sổ đen nào hiện ra — đó là bình thường.
- Mở lại UdemyTranscript.vbs khi app đang chạy: chỉ mở thêm tab trình duyệt,
  không chạy trùng.


2. ĐĂNG NHẬP UDEMY (làm 1 lần)
------------------------------
- Mở udemy.com trên trình duyệt, đăng nhập như bình thường.
- Bấm F12 → tab Application (Chrome/Edge) → Cookies → https://www.udemy.com
  (tài khoản công ty: https://<tên-công-ty>.udemy.com).
- Tìm dòng access_token, copy cột Value, dán vào ô "Đăng nhập Udemy" trên app → Lưu.
- Token hết hạn thì làm lại bước này.


3. TẢI KHOÁ HỌC
---------------
- Dán link khoá (vd https://www.udemy.com/course/ten-khoa-hoc/) → bấm Tải.
- Xong thì bấm "📖 Đọc trên trình duyệt" ở danh sách khoá bên dưới.
- Bấm "Cập nhật" để tải phần mới — bài/file đã có sẽ được bỏ qua.


4. DỮ LIỆU NẰM Ở ĐÂU
--------------------
- Thư mục  data\courses\<tên-khoá>\  (bấm "📂 Thư mục dữ liệu" trên app để mở):
    index.html              trang chủ khoá — mở thẳng bằng trình duyệt cũng đọc được
    transcript.en.html/.md  transcript gộp cả khoá
    OVERVIEW.md             tổng quan khoá
    resources\              file đính kèm
- Token đăng nhập lưu ở  data\token.txt  — đừng gửi thư mục data\ cho người khác.
- Nâng cấp lên bản mới: giải nén bản mới, rồi copy thư mục data\ cũ sang.


5. TẮT ỨNG DỤNG
---------------
- Bấm nút "⏻ Tắt ứng dụng" góc trên bên phải trang web.
- Chỉ đóng tab trình duyệt thì app vẫn chạy ngầm (mở lại .vbs là vào được ngay).


6. KHI GẶP LỖI
--------------
- Xem file  app.log  trong thư mục ứng dụng (ghi lại mỗi lần chạy).
- Hoặc chạy  start.bat  để thấy log trực tiếp trên cửa sổ console.
- Windows SmartScreen / antivirus có thể hỏi lần đầu khi chạy .vbs — chọn
  "More info" → "Run anyway" (ứng dụng chỉ chạy trên máy bạn, không mở cổng ra mạng ngoài).
