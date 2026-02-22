#!/usr/bin/env python3
"""
Instagram Following Manager
----------------------------
Analyse your Instagram following/followers data and optionally unfollow
accounts that don't follow you back.

Usage:
  main.py analyse --export-dir DIR [--export-csv] [--enrich]
  main.py unfollow (--export-dir DIR | --list FILE) [--dry-run] [--export-csv]
  main.py (-h | --help)

Options:
  --export-dir DIR  Path to your Instagram data export directory.
  --list FILE       Text file with one username per line to unfollow.
  --export-csv      Save results to CSV files in the reports/ directory.
  --enrich          Fetch extra profile data (bio, is_business, last post date)
                    for non-followers via the Instagram API. Requires credentials
                    (INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD env vars or prompt).
  --dry-run         Show what would be unfollowed without making any changes.
  -h --help         Show this screen.

Examples:
  # Analyse only (no login required)
  python main.py analyse --export-dir ./instagram_export

  # Export non-followers to CSV
  python main.py analyse --export-dir ./instagram_export --export-csv

  # Interactively unfollow non-followers
  python main.py unfollow --export-dir ./instagram_export

  # Unfollow from a pre-made list file (one username per line)
  python main.py unfollow --list usernames.txt

  # Dry run (shows what would be unfollowed, no actual requests)
  python main.py unfollow --export-dir ./instagram_export --dry-run
"""

import logging
import os
import sys
from pathlib import Path

from docopt import docopt
from dotenv import load_dotenv

from instagram.parser import load_following, load_followers, compute_non_followers
from instagram.reporter import export_csv, export_unfollow_results, print_summary

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subcommand: analyse
# ---------------------------------------------------------------------------

def cmd_analyse(args: dict) -> None:
    print(f"Loading data from: {args['--export-dir']}")
    following = load_following(args['--export-dir'])
    followers = load_followers(args['--export-dir'])
    non_followers = compute_non_followers(following, followers)

    print_summary(following, followers, non_followers)

    if non_followers:
        print("Accounts you follow that don't follow back:")
        for i, account in enumerate(non_followers, 1):
            print(f"  {i:3}. @{account.username}")

    if args['--enrich'] and non_followers:
        ig_username = os.environ.get("INSTAGRAM_USERNAME") or input("Instagram username: ").strip()
        ig_password = os.environ.get("INSTAGRAM_PASSWORD") or input("Instagram password: ").strip()
        totp_secret = os.environ.get("INSTAGRAM_TOTP_SECRET") or None

        from instagram.manager import InstagramManager
        manager = InstagramManager(ig_username, ig_password, totp_secret)

        print("Logging in to fetch profile data...")
        manager.login()

        print(f"\nEnriching {len(non_followers)} non-follower account(s)...")

        def enrich_progress(uname, idx, total):
            print(f"  [{idx + 1}/{total}] Fetching @{uname}...")

        manager.enrich_accounts(non_followers, progress_callback=enrich_progress)
        print()

    if args['--export-csv']:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = export_csv(following, f"following_{ts}.csv")
        print(f"\nFull following list saved to: {path}")
        path = export_csv(non_followers, f"non_followers_{ts}.csv")
        print(f"Non-followers list saved to:  {path}")


# ---------------------------------------------------------------------------
# Subcommand: unfollow
# ---------------------------------------------------------------------------

def cmd_unfollow(args: dict) -> None:
    # Build the target list
    if args['--list']:
        list_path = Path(args['--list'])
        if not list_path.exists():
            sys.exit(f"Error: file not found: {list_path}")
        usernames = [
            line.strip().lstrip("@")
            for line in list_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    elif args['--export-dir']:
        print(f"Loading data from: {args['--export-dir']}")
        following = load_following(args['--export-dir'])
        followers = load_followers(args['--export-dir'])
        non_followers = compute_non_followers(following, followers)
        print_summary(following, followers, non_followers)

        if not non_followers:
            print("Everyone you follow also follows you back. Nothing to do.")
            return

        print(f"Found {len(non_followers)} account(s) that don't follow you back.")
        usernames = [a.username for a in non_followers]
    else:
        sys.exit("Error: provide --export-dir or --list.")

    if not usernames:
        print("No accounts to unfollow.")
        return

    if args['--dry-run']:
        print(f"\n[DRY RUN] Would unfollow {len(usernames)} account(s):")
        for u in usernames:
            print(f"  @{u}")
        return

    # Confirm before proceeding
    print(f"\nAbout to unfollow {len(usernames)} account(s).")
    print("NOTE: This uses conservative rate limiting (20-45s between unfollows)")
    print("      to reduce the risk of your account being flagged.")
    confirm = input("Continue? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    # Login
    username = os.environ.get("INSTAGRAM_USERNAME") or input("Instagram username: ").strip()
    password = os.environ.get("INSTAGRAM_PASSWORD") or input("Instagram password: ").strip()
    totp_secret = os.environ.get("INSTAGRAM_TOTP_SECRET") or None

    from instagram.manager import InstagramManager
    manager = InstagramManager(username, password, totp_secret)

    print("Logging in...")
    manager.login()

    def progress(uname, status, idx, total):
        icon = {"ok": "✓", "not_found": "?", "error": "✗", "dry_run": "~"}.get(status, " ")
        print(f"  [{idx+1}/{total}] {icon} @{uname} — {status}")

    print(f"\nUnfollowing {len(usernames)} account(s)...\n")
    results = manager.unfollow_batch(usernames, dry_run=False, progress_callback=progress)

    # Summary
    ok = sum(1 for s in results.values() if s == "ok")
    skipped = sum(1 for s in results.values() if s == "not_found")
    errors = sum(1 for s in results.values() if s.startswith("error"))
    print(f"\nDone. Unfollowed: {ok}  Skipped (not found): {skipped}  Errors: {errors}")

    if args['--export-csv']:
        path = export_unfollow_results(results)
        print(f"Results saved to: {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = docopt(__doc__)

    if args['analyse']:
        cmd_analyse(args)
    elif args['unfollow']:
        cmd_unfollow(args)


if __name__ == "__main__":
    main()
