"""
Generate CSV reports from parsed Instagram data.
"""

import csv
import os
from datetime import datetime
from pathlib import Path

from .parser import Account


def _ensure_reports_dir(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


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
    output_dir = Path(output_dir)
    _ensure_reports_dir(output_dir)
    path = output_dir / filename

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["username", "profile_url", "followed_at"])
        writer.writeheader()
        for account in accounts:
            writer.writerow(
                {
                    "username": account.username,
                    "profile_url": account.profile_url,
                    "followed_at": (
                        account.followed_at.isoformat() if account.followed_at else ""
                    ),
                }
            )

    return path


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
    output_dir = Path(output_dir)
    _ensure_reports_dir(output_dir)
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
    print(f"  Not following back: {len(non_followers):>3}")
    print("=" * 40)
    print()
