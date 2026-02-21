"""
Instagram action manager using instagrapi.

Handles login (with session persistence and optional 2FA), and provides
controlled unfollow functionality with rate-limiting to reduce ban risk.
"""

import functools
import json
import os
import time
import random
import logging
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    TwoFactorRequired,
    ClientError,
    UserNotFound,
)

logger = logging.getLogger(__name__)

SESSION_FILE = Path("session.json")

# Conservative rate limits to avoid triggering Instagram's bot detection.
# Adjust at your own risk — more aggressive = higher ban probability.
MIN_DELAY_SECONDS = 20
MAX_DELAY_SECONDS = 45
BATCH_SIZE = 10          # pause after every N unfollows
BATCH_PAUSE_SECONDS = 300  # 5 minutes between batches


def _require_login(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not self._logged_in:
            raise RuntimeError("Not logged in. Call login() first.")
        return method(self, *args, **kwargs)
    return wrapper


class InstagramManager:
    def __init__(self, username: str, password: str, totp_secret: str | None = None):
        self.username = username
        self.password = password
        self.totp_secret = totp_secret
        self.client = Client()
        self._logged_in = False

    # ------------------------------------------------------------------
    # Login / session management
    # ------------------------------------------------------------------

    def login(self) -> None:
        """Log in to Instagram, reusing a saved session when possible."""
        if SESSION_FILE.exists():
            logger.info("Loading saved session from %s", SESSION_FILE)
            self.client.load_settings(SESSION_FILE)
            self.client.login(self.username, self.password)
            try:
                self.client.get_timeline_feed()
                self._logged_in = True
                logger.info("Resumed session successfully.")
                return
            except LoginRequired:
                logger.warning("Saved session expired, logging in fresh.")
                self.client = Client()

        self._fresh_login()

    def _fresh_login(self) -> None:
        if self.totp_secret:
            self.client.totp_generate_code(self.totp_secret)

        try:
            self.client.login(self.username, self.password)
        except TwoFactorRequired:
            if not self.totp_secret:
                code = input("Enter your 2FA code: ").strip()
            else:
                code = self.client.totp_generate_code(self.totp_secret)
            self.client.login(self.username, self.password, verification_code=code)

        self.client.dump_settings(SESSION_FILE)
        self._logged_in = True
        logger.info("Logged in and session saved to %s", SESSION_FILE)

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    @_require_login
    def get_user_id(self, username: str) -> int:
        """Resolve a username to its numeric Instagram user ID."""
        try:
            user = self.client.user_info_by_username(username)
            return user.pk
        except UserNotFound:
            raise ValueError(f"User not found: @{username}")

    # ------------------------------------------------------------------
    # Unfollow
    # ------------------------------------------------------------------

    @_require_login
    def unfollow(self, username: str) -> bool:
        """
        Unfollow a single account by username.

        Returns True on success, False if the account was not found.
        """
        try:
            user_id = self.get_user_id(username)
            self.client.user_unfollow(user_id)
            logger.info("Unfollowed @%s", username)
            return True
        except ValueError:
            logger.warning("Skipped @%s — account not found.", username)
            return False
        except ClientError as e:
            logger.error("Error unfollowing @%s: %s", username, e)
            raise

    @_require_login
    def unfollow_batch(
        self,
        usernames: list[str],
        dry_run: bool = False,
        progress_callback=None,
    ) -> dict[str, str]:
        """
        Unfollow a list of accounts with rate limiting.

        Args:
            usernames:         List of usernames to unfollow.
            dry_run:           If True, log actions without actually unfollowing.
            progress_callback: Optional callable(username, status, index, total).

        Returns:
            Dict mapping username -> status ("ok", "not_found", "error", "dry_run").
        """
        results: dict[str, str] = {}
        total = len(usernames)

        for i, username in enumerate(usernames):
            if progress_callback:
                progress_callback(username, "pending", i, total)

            if dry_run:
                logger.info("[DRY RUN] Would unfollow @%s", username)
                results[username] = "dry_run"
                if progress_callback:
                    progress_callback(username, "dry_run", i, total)
                continue

            try:
                success = self.unfollow(username)
                results[username] = "ok" if success else "not_found"
                if progress_callback:
                    progress_callback(username, results[username], i, total)
            except ClientError as e:
                results[username] = f"error: {e}"
                if progress_callback:
                    progress_callback(username, "error", i, total)
                logger.error("Stopping batch due to API error: %s", e)
                break

            # Rate limiting
            if (i + 1) % BATCH_SIZE == 0 and (i + 1) < total:
                logger.info(
                    "Pausing %ds after %d unfollows to avoid rate limits...",
                    BATCH_PAUSE_SECONDS,
                    BATCH_SIZE,
                )
                time.sleep(BATCH_PAUSE_SECONDS)
            else:
                delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                logger.debug("Waiting %.1fs before next unfollow.", delay)
                time.sleep(delay)

        return results
