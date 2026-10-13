UDEMY TRANSCRIPT — PORTABLE BUILD FOR WINDOWS
=============================================
(Bản tiếng Việt: README_USER.vi.txt)

Download the transcripts (English/Vietnamese captions), course overview and
attached files (pdf, docx...) of Udemy courses you own, then read them right in
your browser. No Python or Docker needed — everything is inside this folder.


1. RUN THE APP
--------------
- Extract the ZIP into a folder with a SHORT path (e.g. D:\UdemyTranscript).
  Do NOT run it from inside the ZIP.
- Double-click  UdemyTranscript.vbs
  → your browser opens http://localhost:8097 (if that port is busy: 8098, 8099...).
- No black console window appears — that is expected.
- Opening UdemyTranscript.vbs again while the app is running just opens another
  browser tab; it never starts a second copy.
- Switch the interface language with the EN | VI buttons at the top right.


2. LOG IN TO UDEMY (once)
-------------------------
- Open udemy.com in your browser and log in as usual.
- Press F12 → Application tab (Chrome/Edge) → Cookies → https://www.udemy.com
  (company accounts: https://<company>.udemy.com).
- Find the access_token row, copy its Value, paste it into the "Udemy login"
  box in the app → Save.
- When the token expires, repeat this step.


3. DOWNLOAD A COURSE
--------------------
- Paste the course link (e.g. https://www.udemy.com/course/course-name/) → Download.
- When it finishes, click "📖 Read in browser" in the course list below.
- Click "Update" to fetch new content — lectures/files you already have are skipped.


4. WHERE YOUR DATA LIVES
------------------------
- Folder  data\courses\<course-name>\  (click "📂 Data folder" in the app to open it):
    index.html              course home page — also works opened directly in a browser
    transcript.en.html/.md  combined transcript of the whole course
    OVERVIEW.md             course overview
    resources\              attached files
- Your login token is stored in  data\token.txt  — never send the data\ folder to anyone.
- Upgrading: extract the new version, then copy your old data\ folder into it.


5. QUIT THE APP
---------------
- Click "⏻ Quit app" at the top right of the web page.
- Just closing the browser tab keeps the app running in the background
  (open the .vbs again to get back in instantly).


6. TROUBLESHOOTING
------------------
- Check  app.log  in the application folder (rewritten on every start).
- Or run  start.bat  to watch the log live in a console window.
- Windows SmartScreen / antivirus may ask the first time you run the .vbs —
  choose "More info" → "Run anyway" (the app only runs on your computer and
  does not open any port to the outside network).
