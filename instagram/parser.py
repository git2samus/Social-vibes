"""
Parse Instagram data export files to extract following/follower lists.

Instagram exports your data as JSON files. Download yours at:
  Settings -> Your activity -> Download your information

The relevant files are in:
  connections/followers_and_following/
    - following.json
    - followers_1.json  (may be split: followers_2.json, etc.)
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Account:
    username: str
    profile_url: str
    followed_at: datetime | None
    last_post_at: datetime | None = None
    biography: str = ""
    is_business: bool | None = None


def _extract_accounts(data: list[dict]) -> list[Account]:
    """Extract accounts from the Instagram export JSON structure."""
    accounts = []
    for entry in data:
        username = entry.get("title", "")
        string_list = entry.get("string_list_data", [])
        for item in string_list:
            href = item.get("href", "")
            timestamp = item.get("timestamp")
            if username:
                followed_at = datetime.fromtimestamp(timestamp) if timestamp else None
                accounts.append(Account(username=username, profile_url=href, followed_at=followed_at))
    return accounts


def load_following(export_dir: str | Path) -> list[Account]:
    """
    Load the list of accounts you follow from the Instagram data export.

    Args:
        export_dir: Path to your Instagram export directory (the root folder
                    containing the 'connections' subdirectory, or the
                    'followers_and_following' subdirectory directly).

    Returns:
        List of Account objects representing accounts you follow.
    """
    export_dir = Path(export_dir)
    candidates = [
        export_dir / "connections" / "followers_and_following" / "following.json",
        export_dir / "followers_and_following" / "following.json",
        export_dir / "following.json",
    ]

    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        checked = "\n  ".join(str(p) for p in candidates)
        raise FileNotFoundError(
            f"Could not find following.json. Looked in:\n  {checked}\n"
            "Make sure you point to your Instagram export directory."
        )

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    # The top-level key is "relationships_following"
    entries = raw.get("relationships_following", raw) if isinstance(raw, dict) else raw
    return _extract_accounts(entries)


def load_followers(export_dir: str | Path) -> list[Account]:
    """
    Load the list of accounts that follow you from the Instagram data export.

    Instagram may split followers across multiple files (followers_1.json,
    followers_2.json, ...).

    Args:
        export_dir: Path to your Instagram export directory.

    Returns:
        List of Account objects representing your followers.
    """
    export_dir = Path(export_dir)

    # Locate the followers_and_following directory
    base_candidates = [
        export_dir / "connections" / "followers_and_following",
        export_dir / "followers_and_following",
        export_dir,
    ]
    base = next((p for p in base_candidates if p.is_dir()), export_dir)

    # Collect all followers_*.json files
    follower_files = sorted(base.glob("followers_*.json"))
    if not follower_files:
        single = base / "followers.json"
        if single.exists():
            follower_files = [single]
        else:
            raise FileNotFoundError(
                f"Could not find any followers JSON files in: {base}\n"
                "Expected files named followers_1.json, followers_2.json, etc."
            )

    accounts: list[Account] = []
    for path in follower_files:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        entries = raw if isinstance(raw, list) else raw.get("relationships_followers", raw)
        accounts.extend(_extract_accounts(entries))

    return accounts


def compute_non_followers(following: list[Account], followers: list[Account]) -> list[Account]:
    """Return accounts that follow you but you don't follow back."""
    following_usernames = {a.username.lower() for a in following}
    return [a for a in followers if a.username.lower() not in following_usernames]
