#!/usr/bin/env python3
"""
Instagram Following Manager
----------------------------
Analyse your Instagram following/followers data and optionally unfollow
accounts that don't follow you back.

Usage:
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

import argparse
import logging
import os
import sys
from pathlib import Path

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

def cmd_analyse(args: argparse.Namespace) -> None:
    print(f"Loading data from: {args.export_dir}")
    following = load_following(args.export_dir)
    followers = load_followers(args.export_dir)
    non_followers = compute_non_followers(following, followers)

    print_summary(following, followers, non_followers)

    if non_followers:
        print("Accounts you follow that don't follow back:")
        for i, account in enumerate(non_followers, 1):
            print(f"  {i:3}. @{account.username}")

    if args.export_csv:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = export_csv(following, f"following_{ts}.csv")
        print(f"\nFull following list saved to: {path}")
        path = export_csv(non_followers, f"non_followers_{ts}.csv")
        print(f"Non-followers list saved to:  {path}")


# ---------------------------------------------------------------------------
# Subcommand: unfollow
# ---------------------------------------------------------------------------

def cmd_unfollow(args: argparse.Namespace) -> None:
    # Build the target list
    if args.list:
        list_path = Path(args.list)
        if not list_path.exists():
            sys.exit(f"Error: file not found: {list_path}")
        usernames = [
            line.strip().lstrip("@")
            for line in list_path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    elif args.export_dir:
        print(f"Loading data from: {args.export_dir}")
        following = load_following(args.export_dir)
        followers = load_followers(args.export_dir)
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

    if args.dry_run:
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

    if args.export_csv:
        path = export_unfollow_results(results)
        print(f"Results saved to: {path}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage your Instagram following list.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- analyse ---
    p_analyse = sub.add_parser("analyse", help="Analyse following vs followers.")
    p_analyse.add_argument(
        "--export-dir",
        required=True,
        metavar="DIR",
        help="Path to your Instagram data export directory.",
    )
    p_analyse.add_argument(
        "--export-csv",
        action="store_true",
        help="Save results to CSV files in the reports/ directory.",
    )

    # --- unfollow ---
    p_unfollow = sub.add_parser("unfollow", help="Unfollow accounts.")
    source = p_unfollow.add_mutually_exclusive_group()
    source.add_argument(
        "--export-dir",
        metavar="DIR",
        help="Path to your Instagram data export; unfollows non-followers.",
    )
    source.add_argument(
        "--list",
        metavar="FILE",
        help="Text file with one username per line to unfollow.",
    )
    p_unfollow.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be unfollowed without making any changes.",
    )
    p_unfollow.add_argument(
        "--export-csv",
        action="store_true",
        help="Save unfollow results to a CSV file.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyse":
        cmd_analyse(args)
    elif args.command == "unfollow":
        cmd_unfollow(args)


if __name__ == "__main__":
    main()
