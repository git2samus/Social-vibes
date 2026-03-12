#!/usr/bin/env python3
"""
Instagram Following Manager
----------------------------
Analyze your Instagram following/followers data and optionally unfollow
accounts that don't follow you back.

Usage:
  main.py analyze --export-dir DIR [--export-csv] [--enrich] [--logout] [--list FILE | --sample N] [--verbose]
  main.py unfollow (--export-dir DIR | --list FILE) [--dry-run] [--export-csv] [--logout] [--sample N] [--verbose]
  main.py (-h | --help)

Options:
  --export-dir DIR  Path to your Instagram data export directory.
  --list FILE       Text file with one username per line.
                    For analyze: restrict enrichment to those accounts.
                    For unfollow: use as the target list instead of the export.
  --export-csv      Save results to CSV files in the reports/ directory.
  --enrich          Fetch extra profile data (bio, is_business, last post date)
                    for everyone you follow by opening a real browser session.
                    A Chromium window will open; log in once and the session is
                    saved for future runs.
  --logout          Before the browser session starts, check for an active
                    Instagram session and log it out so you can sign in as a
                    different account.  Has no effect when no session exists.
  --dry-run         Show what would be unfollowed without making any changes.
  --sample N        Only process the first N accounts (useful for quick tests).
  --verbose         Enable verbose (DEBUG-level) logging for detailed output,
                    including all Playwright browser interactions and timings.
  -h --help         Show this screen.

Examples:
  # Analyze only (no login required)
  python main.py analyze --export-dir ./instagram_export

  # Export non-followers to CSV
  python main.py analyze --export-dir ./instagram_export --export-csv

  # Interactively unfollow non-followers
  python main.py unfollow --export-dir ./instagram_export

  # Unfollow from a pre-made list file (one username per line)
  python main.py unfollow --list usernames.txt

  # Dry run (shows what would be unfollowed, no actual requests)
  python main.py unfollow --export-dir ./instagram_export --dry-run

  # Quick test on just 5 accounts
  python main.py analyze --export-dir ./instagram_export --enrich --sample 5
  python main.py unfollow --export-dir ./instagram_export --dry-run --sample 5

  # Enrich specific accounts from a file
  python main.py analyze --export-dir ./instagram_export --enrich --list accounts.txt

  # Switch Instagram account before running
  python main.py unfollow --export-dir ./instagram_export --logout
"""

import logging
import sys
from pathlib import Path

from docopt import docopt
from dotenv import load_dotenv

from instagram.parser import load_following, load_followers, compute_non_followers
from instagram.reporter import export_csv, export_unfollow_results, print_accounts_table, print_summary

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _load_usernames_file(file_arg: str) -> list[str]:
    """Parse a username list file (one per line, # comments, leading @ stripped)."""
    path = Path(file_arg)
    try:
        text = path.read_text()
    except FileNotFoundError:
        sys.exit(f"Error: file not found: {path}")
    return [
        line.strip().lstrip("@")
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


# ---------------------------------------------------------------------------
# Subcommand: analyze
# ---------------------------------------------------------------------------

def cmd_analyze(args: dict) -> None:
    print(f"Loading data from: {args['--export-dir']}")
    following = load_following(args['--export-dir'])
    followers = load_followers(args['--export-dir'])
    non_followers = compute_non_followers(following, followers)

    print_summary(following, followers, non_followers)

    enrich_target = None
    if args['--enrich'] and following:
        from instagram.browser_manager import BrowserManager

        enrich_target = following
        if args['--list']:
            usernames = set(_load_usernames_file(args['--list']))
            enrich_target = [a for a in enrich_target if a.username in usernames]
            print(f"(Restricted to {len(enrich_target)} account(s) from {args['--list']})")
        elif args['--sample']:
            n = int(args['--sample'])
            enrich_target = enrich_target[:n]
            print(f"(Sampling first {n} following accounts)")

        print(f"\nEnriching {len(enrich_target)} following account(s)...")

        def enrich_progress(uname, idx, total):
            print(f"  [{idx + 1}/{total}] Fetching @{uname}...")

        print("Opening browser...")
        with BrowserManager() as manager:
            if args['--logout']:
                manager.logout()
            manager.login()
            manager.enrich_accounts(enrich_target, progress_callback=enrich_progress)
        print()

    if args['--export-csv']:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = export_csv(following, f"following_{ts}.csv")
        print(f"\nFull following list saved to: {path}")
        path = export_csv(non_followers, f"non_followers_{ts}.csv")
        print(f"Non-followers list saved to:  {path}")
    else:
        if enrich_target:
            print_accounts_table(enrich_target, title=f"Following — enriched ({len(enrich_target)}):")
        print_accounts_table(non_followers, title="Accounts you follow that don't follow back:")


# ---------------------------------------------------------------------------
# Subcommand: unfollow
# ---------------------------------------------------------------------------

def cmd_unfollow(args: dict) -> None:
    # Build the target list
    if args['--list']:
        usernames = _load_usernames_file(args['--list'])
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

    if args['--sample']:
        n = int(args['--sample'])
        usernames = usernames[:n]
        print(f"(Sampling first {n} accounts)")

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
    print("NOTE: Uses conservative rate limiting (20-45s between unfollows)")
    print("      to reduce the risk of your account being flagged.")
    confirm = input("Continue? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    from instagram.browser_manager import BrowserManager

    def progress(uname, status, idx, total):
        icon = {"ok": "✓", "not_found": "?", "error": "✗", "dry_run": "~"}.get(status, " ")
        print(f"  [{idx+1}/{total}] {icon} @{uname} — {status}")

    print("Opening browser...")
    with BrowserManager() as manager:
        if args['--logout']:
            manager.logout()
        manager.login()
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

    if args['--verbose']:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled.")

    if args['analyze']:
        cmd_analyze(args)
    elif args['unfollow']:
        cmd_unfollow(args)


if __name__ == "__main__":
    main()
