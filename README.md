# Udemy Transcript

**English** · [Tiếng Việt](README.vi.md)

Download the **transcripts**, **course overview** and **attached files** (pdf, docx…) of the Udemy courses you own, then read them right in your browser — with a table of contents and an English ⇄ Vietnamese switch that keeps you on the lecture you were reading.

Paste a course link → click **Download** → click **📖 Read in browser**. That's it.

> ⚠️ For courses **you own**, for personal study only. Course content is copyrighted by its instructors/Udemy — don't share the downloaded files. You are responsible for following [Udemy's Terms of Use](https://www.udemy.com/terms/) (and your company's rules if you use Udemy Business).
>
> Independent project, **not affiliated with, sponsored or endorsed by Udemy**. "Udemy" is a trademark of Udemy, Inc. The app does not download videos and does not bypass DRM — it only fetches captions and attached files your account can already view/download.

## Features

- **Per-lecture transcripts** as `.txt` and `.srt` (with timestamps), plus **one combined file for the whole course** per language — handy for asking ChatGPT/Claude to summarise or quiz you.
- **Pick caption languages** (English + Vietnamese by default). Instructor-uploaded captions are preferred; Udemy's machine translations are clearly flagged.
- **Attached files** from every lecture, including articles, organised by section.
- **Course overview**: description, "What you'll learn", requirements, target audience, instructors, rating…
- **HTML reading pages**: course home (contents + links to every lecture and attachment), overview page, and transcript pages with a contents sidebar that follows your reading position. Links are relative, so they also work opened straight from disk or from the zip.
- **Re-runs skip what you have**: existing lectures/files are left alone, only new content is fetched.
- **English / Vietnamese interface** — switch with the **EN | VI** buttons; logs, error messages and the course reading pages follow.
- Works with **Udemy Business** (company accounts, `<company>.udemy.com`).
- Fast: captions are fetched straight from the API — a ~60-lecture course takes seconds, no browser automation.

## Install & run

Pick one of three ways.

### 1. Windows — portable build (nothing to install)

Download `UdemyTranscript-<version>-portable.zip`, extract it into a folder with a **short path** (e.g. `D:\UdemyTranscript`), double-click **`UdemyTranscript.vbs`** → your browser opens `http://localhost:8097`. Quit with the **⏻ Quit app** button on the page. Full instructions are in the bundle's `README_USER.txt`.

Build the bundle yourself (on Windows, needs Python 3.12 and internet):

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

Open http://localhost:8096. Your data lives in `./data` on the host.

### 3. Python

```bash
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8096
```

## Logging in to Udemy

The app uses the `access_token` cookie from your own browser (no password needed):

1. Log in to udemy.com as usual.
2. F12 → **Application** tab (Chrome/Edge) or **Storage** (Firefox) → **Cookies** → `https://www.udemy.com` (company accounts: `https://<company>.udemy.com`).
3. Copy the value of the `access_token` row, paste it into the **Udemy login** box in the app → **Save**.

Repeat when the token expires. If Cloudflare blocks you, paste the whole `Cookie` request header (Network tab) instead of just `access_token`. You can also preset it with the `UDEMY_ACCESS_TOKEN` environment variable instead of pasting it in the web UI.

## Downloaded data

```
data/
  token.txt                         ← your login token — never share it
  settings.json                     interface language
  courses/<course-name>/
    index.html                      ← open this to read
    overview.html, transcript.en.html, transcript.vi.html
    OVERVIEW.md                     course overview
    transcript.en.md, transcript.vi.md   combined transcripts
    CONTENTS.md                     contents, which lectures have which caption languages
    en/01.01 <lecture title>.txt | .srt
    vi/...
    resources/<section>/<attached file>
    resources/INDEX.md
```

## Command line

```bash
python cli.py "https://www.udemy.com/course/<course-name>/" [--langs en,vi] [--force] [--no-resources]
python render.py --all        # rebuild the HTML pages from downloaded data, without calling Udemy
```

`--force` re-downloads lectures you already have; `--no-resources` skips attached files.

## Configuration

| Environment variable | Default | |
|---|---|---|
| `UDEMY_ACCESS_TOKEN` | — | Login token (a token pasted in the web UI takes precedence) |
| `APP_LANG` | `en` | Interface language until one is picked in the web UI (`en` / `vi`) |
| `TRANSCRIPT_LANGS` | `en,vi` | Default **caption** languages to download |
| `TRANSCRIPT_WORKERS` | `4` | Parallel downloads |
| `DATA_DIR` | `./data` | Where data is stored |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Host names allowed to reach the web UI |

## Security

The app is meant to run **on your own computer**:

- The Docker setup listens on `127.0.0.1` only; requests with an unknown Host header are rejected (DNS-rebinding protection), and body-less commands (quit, open folder) require a custom header so other websites can't trigger them.
- The token is never returned by the API and is only ever sent to `udemy.com` / `*.udemy.com`.
- Content from Udemy is escaped when building HTML; the reading pages block all network requests from scripts (CSP `connect-src 'none'`).

**Do not** expose the app to the network (e.g. `-p 0.0.0.0:...`) — it has no login of its own, so anyone who reaches the page can use your token.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Architecture notes, verified Udemy endpoints and the fix history are in [`CLAUDE.md`](CLAUDE.md) (Vietnamese). Interface strings live in `i18n.py` (server side) and in the `STR` table of `static/index.html` (web UI); both are checked by tests for missing keys and mismatched placeholders.

## Limitations

- Only **video** lectures get transcripts; the text of articles, quizzes and coding exercises isn't saved yet (their attached files are).
- Most Vietnamese captions on Udemy are **machine-translated** — treat them as a reference.
- The portable build has no auto-update yet: extract the new version and copy your old `data\` folder into it.

## License

[MIT](LICENSE) © 2026 madu — applies to this repository's **source code**, not to course content downloaded with the app.

## Credits

The original idea comes from [TOA-Anakin/udemy-transcript-downloader](https://github.com/TOA-Anakin/udemy-transcript-downloader) (Node.js + Puppeteer). This is a from-scratch Python rewrite: captions are fetched straight from the API instead of driving a browser, plus attached files, course overview, HTML reading pages and a Windows portable build.
