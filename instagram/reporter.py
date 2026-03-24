"""
Generate CSV reports from parsed Instagram data.
"""

import csv
import functools
import inspect
import os
from datetime import datetime
from pathlib import Path

from .parser import Account


def print_accounts_table(
    accounts: list[Account],
    title: str | None = None,
) -> None:
    """Print a human-readable table of accounts to stdout."""
    if title:
        print(title)
    if not accounts:
        print("  (none)")
        print()
        return

    for i, a in enumerate(accounts, 1):
        extras = []
        if a.followed_at:
            extras.append(f"followed {a.followed_at.strftime('%Y-%m-%d')}")
        if a.last_post_at:
            extras.append(f"last post {a.last_post_at.strftime('%Y-%m-%d')}")
        if a.is_business is not None:
            extras.append("business" if a.is_business else "personal")
        suffix = "  —  " + "  ·  ".join(extras) if extras else ""
        print(f"  {i:3}. @{a.username}{suffix}")
        if a.biography:
            bio = a.biography[:80] + "…" if len(a.biography) > 80 else a.biography
            print(f'       "{bio}"')
    print()


def _ensure_reports_dir(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        output_dir = Path(bound.arguments["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        bound.arguments["output_dir"] = output_dir
        return func(*bound.args, **bound.kwargs)
    return wrapper


_ACCOUNT_FIELDS = [
    "username",
    "profile_url",
    "followed_at",
    "last_post_at",
    "biography",
    "is_business",
]


@_ensure_reports_dir
def export_csv(
    accounts: list[Account],
    filename: str,
    output_dir: str | Path = "reports",
) -> Path:
    """
    Write a list of accounts to a CSV file.

    Args:
        accounts:   List of Account objects to export.
        filename:   Output filename (e.g. "non_followers.csv").
        output_dir: Directory to write the file into (created if needed).

    Returns:
        Path to the written CSV file.
    """
    path = output_dir / filename

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_ACCOUNT_FIELDS)
        writer.writeheader()
        for account in accounts:
            writer.writerow(
                {
                    "username": account.username,
                    "profile_url": account.profile_url,
                    "followed_at": account.followed_at.isoformat() if account.followed_at else "",
                    "last_post_at": account.last_post_at.isoformat() if account.last_post_at else "",
                    "biography": account.biography,
                    "is_business": "" if account.is_business is None else str(account.is_business),
                }
            )

    return path


@_ensure_reports_dir
def export_unfollow_results(
    results: dict[str, str],
    output_dir: str | Path = "reports",
) -> Path:
    """
    Write the results of an unfollow batch operation to a CSV file.

    Args:
        results:    Dict mapping username -> status string.
        output_dir: Directory to write the file into.

    Returns:
        Path to the written CSV file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"unfollow_results_{timestamp}.csv"

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["username", "status"])
        writer.writeheader()
        for username, status in results.items():
            writer.writerow({"username": username, "status": status})

    return path


def print_summary(
    following: list[Account],
    followers: list[Account],
    non_followers: list[Account],
) -> None:
    """Print a summary table to stdout."""
    print()
    print("=" * 40)
    print("  Instagram Following Summary")
    print("=" * 40)
    print(f"  Following:       {len(following):>6}")
    print(f"  Followers:       {len(followers):>6}")
    print(f"  Not followed back:  {len(non_followers):>3}")
    print("=" * 40)
    print()
