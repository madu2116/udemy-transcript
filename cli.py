"""Chạy không cần web UI:
    docker compose exec udemy-transcript python cli.py <course-url> [--langs en,vi] [--force]
"""
import argparse
import sys

import config
from udemy import UdemyError, download_course


def main():
    ap = argparse.ArgumentParser(description="Tải transcript 1 khoá Udemy")
    ap.add_argument("url")
    ap.add_argument("--langs", default=",".join(config.DEFAULT_LANGS))
    ap.add_argument("--force", action="store_true", help="tải lại cả bài đã có")
    ap.add_argument("--no-resources", action="store_true", help="không tải file đính kèm (pdf, docx...)")
    args = ap.parse_args()

    token, _ = config.load_token()
    langs = [x.strip().lower() for x in args.langs.split(",") if x.strip()]
    try:
        meta = download_course(args.url, token, config.COURSES_DIR, langs, force=args.force,
                               resources=not args.no_resources, workers=config.WORKERS)
    except (UdemyError, ValueError) as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Xong → {config.COURSES_DIR / meta['slug']}")


if __name__ == "__main__":
    main()
