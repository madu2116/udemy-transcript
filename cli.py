"""Chạy không cần web UI:
    docker compose exec udemy-transcript python cli.py <course-url> [--langs en,vi] [--force]
"""
import argparse
import sys

import config
from i18n import t
from udemy import UdemyError, download_course


def main():
    ap = argparse.ArgumentParser(description=t("cli_description"))
    ap.add_argument("url")
    ap.add_argument("--langs", default=",".join(config.DEFAULT_LANGS))
    ap.add_argument("--force", action="store_true", help=t("cli_force"))
    ap.add_argument("--no-resources", action="store_true", help=t("cli_no_resources"))
    args = ap.parse_args()

    token, _ = config.load_token()
    langs = [x.strip().lower() for x in args.langs.split(",") if x.strip()]
    try:
        meta = download_course(args.url, token, config.COURSES_DIR, langs, force=args.force,
                               resources=not args.no_resources, workers=config.WORKERS)
    except (UdemyError, ValueError) as e:
        print(t("cli_error", err=e), file=sys.stderr)
        sys.exit(1)
    print(t("cli_done", path=config.display_path(config.COURSES_DIR / meta["slug"])))


if __name__ == "__main__":
    main()
