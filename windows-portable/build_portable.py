"""Build bản Windows portable của udemy-transcript → dist/UdemyTranscript-<version>-portable.zip

    python windows-portable/build_portable.py [version] [--clean]

Viết bằng Python thay vì PowerShell (PowerShell.exe crash khi gọi từ Git Bash trên máy build). Chạy trên Windows: pip đánh giá environment marker theo máy đang chạy (vd click
cần colorama khi sys_platform == "win32"), nên build từ Linux sẽ thiếu/thừa dependency.

Các bước:
  1. runtime/  Python embeddable (tải 1 lần, cache ở windows-portable/.cache/), bật site-packages
  2. deps      pip --target runtime/Lib/site-packages, chỉ wheel win_amd64 cp312; chỉ cài lại khi
               requirements.txt đổi (so hash) hoặc --clean
  3. app/      copy code + static/ (xoá app/ cũ trước)
  4. launcher  launcher.py, UdemyTranscript.vbs, start.bat, README_USER.txt (.bat/.vbs đổi sang CRLF)
  5. smoke     runtime\\python.exe import thử main/render/curl_cffi (DATA_DIR tạm, không đụng data/)
  6. zip       KHÔNG bao giờ đưa data/ (token đăng nhập!), app.log, __pycache__ vào zip — có verify
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

PY_VERSION = "3.12.10"
PY_TAG = "312"
APP = "UdemyTranscript"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATES = HERE / "templates"
CACHE = HERE / ".cache"
DIST = HERE / "dist"
OUT = DIST / APP
RUNTIME = OUT / "runtime"
SITE = RUNTIME / "Lib" / "site-packages"
APP_FILES = ["main.py", "udemy.py", "render.py", "config.py", "cli.py"]
APP_DIRS = ["static"]
LAUNCHER_FILES = ["launcher.py", "UdemyTranscript.vbs", "start.bat", "README_USER.txt"]
CRLF_SUFFIXES = {".bat", ".vbs", ".txt"}
# Không bao giờ đóng gói: dữ liệu người dùng (token!), log, cache bytecode, file tải dở
EXCLUDE_TOP = {"data", "app.log"}
EXCLUDE_NAMES = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".part"}


def step(msg: str):
    print(f"\n=== {msg} ===", flush=True)


def portable_requirements() -> list[str]:
    """requirements.txt của Docker, bỏ extras (uvicorn[standard] kéo uvloop/httptools/watchfiles
    — không cần cho 1 người dùng local)."""
    reqs = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            reqs.append(re.sub(r"\[[^\]]*\]", "", line))
    return reqs


def build_runtime(clean: bool):
    step(f"1/6 Runtime Python {PY_VERSION} embeddable")
    if clean and RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    if (RUNTIME / "pythonw.exe").exists():
        print("    đã có — dùng lại (thêm --clean để tải lại)")
        return
    CACHE.mkdir(exist_ok=True)
    embed = CACHE / f"python-{PY_VERSION}-embed-amd64.zip"
    if not embed.exists():
        url = f"https://www.python.org/ftp/python/{PY_VERSION}/{embed.name}"
        print(f"    tải {url}")
        urllib.request.urlretrieve(url, embed)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(embed) as z:
        z.extractall(RUNTIME)
    # Embeddable Python mặc định tắt site + chỉ dùng sys.path trong ._pth → bật lại site-packages
    pth = RUNTIME / f"python{PY_TAG}._pth"
    lines = pth.read_text(encoding="utf-8").splitlines()
    lines = ["import site" if ln.strip() == "#import site" else ln for ln in lines]
    if "Lib\\site-packages" not in lines:
        lines.insert(len(lines) - 1 if lines and lines[-1] == "import site" else len(lines), "Lib\\site-packages")
    pth.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    print(f"    {pth.name}: {' | '.join(lines)}")


def install_deps(clean: bool):
    step("2/6 Dependencies")
    reqs = portable_requirements()
    digest = hashlib.sha256(("\n".join(reqs) + PY_VERSION).encode()).hexdigest()
    stamp = SITE / ".requirements.sha256"
    if not clean and stamp.exists() and stamp.read_text().strip() == digest:
        print(f"    không đổi ({', '.join(reqs)}) — bỏ qua")
        return
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
           "--target", str(SITE), "--platform", "win_amd64", "--python-version", PY_TAG,
           "--implementation", "cp", "--only-binary=:all:", *reqs]
    print("    " + " ".join(cmd[3:]))
    subprocess.run(cmd, check=True)
    for junk in SITE.glob("bin"):  # script entry point của pip --target, không dùng
        shutil.rmtree(junk)
    stamp.write_text(digest)


def copy_app():
    step("3/6 Code ứng dụng → app/")
    app_dir = OUT / "app"
    if app_dir.exists():
        shutil.rmtree(app_dir)
    app_dir.mkdir()
    for f in APP_FILES:
        shutil.copy2(ROOT / f, app_dir / f)
    for d in APP_DIRS:
        shutil.copytree(ROOT / d, app_dir / d, ignore=shutil.ignore_patterns("__pycache__"))
    print(f"    {', '.join(APP_FILES + [d + '/' for d in APP_DIRS])}")


def copy_launcher():
    step("4/6 Launcher")
    for f in LAUNCHER_FILES:
        src, dst = TEMPLATES / f, OUT / f
        if dst.suffix.lower() in CRLF_SUFFIXES:
            text = src.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
            # .bat/.vbs giữ ASCII (cmd/wscript đọc theo codepage ANSI); README là UTF-8 có BOM cho Notepad cũ
            enc = "utf-8-sig" if dst.suffix.lower() == ".txt" else "ascii"
            dst.write_bytes(text.encode(enc))
        else:
            shutil.copy2(src, dst)
    print(f"    {', '.join(LAUNCHER_FILES)}")


def smoke_test():
    step("5/6 Smoke test runtime")
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DATA_DIR": tmp, "PYTHONIOENCODING": "utf-8"}
        # ._pth của embeddable chỉ dùng đúng các path liệt kê → phải tự thêm app/ và thư mục gốc
        code = ("import sys; sys.path[:0] = ['app', '.']; import main, render, udemy, curl_cffi, launcher; "
                "from curl_cffi import requests; "
                "print('python', sys.version.split()[0], '| curl_cffi', curl_cffi.__version__, '| routes', len(main.app.routes))")
        r = subprocess.run([str(RUNTIME / "python.exe"), "-c", code], cwd=OUT, env=env,
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            raise SystemExit("Smoke test THẤT BẠI")
        print("    " + r.stdout.strip())


def _included(rel: Path) -> bool:
    parts = rel.parts
    if parts[0] in EXCLUDE_TOP:
        return False
    return not (set(parts) & EXCLUDE_NAMES) and rel.suffix not in EXCLUDE_SUFFIXES


def make_zip(version: str) -> Path:
    step("6/6 Đóng gói")
    for old in DIST.glob(f"{APP}-*-portable.zip"):
        old.unlink()
    out = DIST / f"{APP}-{version}-portable.zip"
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(OUT.rglob("*")):
            rel = f.relative_to(OUT)
            if f.is_file() and _included(rel):
                z.write(f, Path(APP) / rel)
                count += 1
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None, "ZIP hỏng"
        names = z.namelist()
    leaked = [n for n in names if n.split("/")[1] in EXCLUDE_TOP or n.endswith("token.txt")]
    assert not leaked, f"ZIP chứa dữ liệu người dùng: {leaked[:3]}"
    for must in ("runtime/pythonw.exe", "app/main.py", "app/static/index.html", "launcher.py", "UdemyTranscript.vbs"):
        assert f"{APP}/{must}" in names, f"ZIP thiếu {must}"
    print(f"    {count} file, {out.stat().st_size / 1024 / 1024:.1f} MB — verify OK (không có data/, token, app.log)")
    return out


def main(argv: list[str]):
    clean = "--clean" in argv
    args = [a for a in argv if not a.startswith("--")]
    version = args[0] if args else "v1.0"
    if os.name != "nt":
        print("⚠ Nên build trên Windows — environment marker của dependency sẽ đánh giá theo máy hiện tại.")
    OUT.mkdir(parents=True, exist_ok=True)
    build_runtime(clean)
    install_deps(clean)
    copy_app()
    copy_launcher()
    smoke_test()
    out = make_zip(version)
    print(f"\nHOÀN TẤT: {out}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main(sys.argv[1:])
