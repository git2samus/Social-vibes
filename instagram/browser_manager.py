"""
Instagram action manager using Playwright browser automation.

Uses a persistent Chromium profile so the user only needs to log in once
manually; subsequent runs reuse the saved cookies automatically.

For the enrich flow, Instagram's internal ``web_profile_info`` JSON endpoint
is intercepted as the browser loads each profile page, giving us structured
data (biography, business flag, last-post timestamp) without having to
parse fragile DOM markup.

For the unfollow flow the browser navigates to each profile and clicks
"Following" → "Unfollow" exactly as a human would.
"""

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)

from .parser import Account

logger = logging.getLogger(__name__)

# Persistent browser profile stored at the project root (git-ignored).
BROWSER_PROFILE_DIR = Path("browser_profile")

INSTAGRAM_URL = "https://www.instagram.com"

# Conservative rate limits — configurable via environment variables.
MIN_DELAY_SECONDS = int(os.getenv("UNFOLLOW_MIN_DELAY", "20"))
MAX_DELAY_SECONDS = int(os.getenv("UNFOLLOW_MAX_DELAY", "45"))
BATCH_SIZE = int(os.getenv("UNFOLLOW_BATCH_SIZE", "10"))
BATCH_PAUSE_SECONDS = int(os.getenv("UNFOLLOW_BATCH_PAUSE", "300"))
ENRICH_MIN_DELAY_SECONDS = int(os.getenv("ENRICH_MIN_DELAY", "3"))
ENRICH_MAX_DELAY_SECONDS = int(os.getenv("ENRICH_MAX_DELAY", "7"))


class BrowserManager:
    """
    Drop-in replacement for InstagramManager that drives a real Chromium
    browser instead of calling Instagram's private API directly.

    Usage::

        with BrowserManager() as manager:
            manager.login()
            manager.enrich_accounts(accounts)

        with BrowserManager() as manager:
            manager.login()
            results = manager.unfollow_batch(usernames)
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._ready = False

    # ------------------------------------------------------------------
    # Context manager — browser lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> "BrowserManager":
        BROWSER_PROFILE_DIR.mkdir(exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 900},
            # Mimic a regular desktop Chrome to reduce fingerprint signals.
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        # Reuse the first tab if the browser restored one; otherwise open new.
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )
        return self

    def __exit__(self, *_) -> None:
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()

    # ------------------------------------------------------------------
    # Login / session check
    # ------------------------------------------------------------------

    def login(self) -> None:
        """
        Navigate to Instagram and verify the session is active.

        If the saved profile already contains valid cookies the feed loads
        immediately and this method returns straight away.  If not, the
        login form will be visible in the browser window and the method
        waits (up to 2 minutes) for the user to complete it manually.
        No credentials are ever passed to this script.
        """
        page = self._page
        page.goto(f"{INSTAGRAM_URL}/", wait_until="domcontentloaded", timeout=30_000)
        # Let React finish rendering the initial view.
        page.wait_for_timeout(1_500)

        login_input = page.query_selector('input[name="username"]')
        if login_input:
            print(
                "\n[Browser] Instagram login required.\n"
                "Please log in to Instagram in the browser window that just opened.\n"
                "Waiting up to 2 minutes for you to complete login..."
            )
            # Wait until the login form disappears (user completed login).
            page.wait_for_selector(
                'input[name="username"]',
                state="detached",
                timeout=120_000,
            )
            # Give the feed a moment to fully settle.
            page.wait_for_timeout(2_000)
            print("[Browser] Logged in successfully.")

        self._ready = True
        logger.info("Browser session ready.")

    def _assert_ready(self) -> None:
        if not self._ready:
            raise RuntimeError("Not ready. Call login() first.")

    # ------------------------------------------------------------------
    # Enrich
    # ------------------------------------------------------------------

    def enrich_accounts(
        self,
        accounts: list[Account],
        progress_callback=None,
    ) -> None:
        """
        Enrich Account objects in-place with live profile data.

        Navigates to each profile page and intercepts the internal
        ``web_profile_info`` API response Instagram fires during page load.
        Falls back to basic DOM extraction if the response is not captured.

        Args:
            accounts:          List of Account objects to enrich (mutated in-place).
            progress_callback: Optional callable(username, index, total).
        """
        self._assert_ready()
        total = len(accounts)
        for i, account in enumerate(accounts):
            if progress_callback:
                progress_callback(account.username, i, total)
            try:
                self._enrich_one(account)
            except Exception as e:
                logger.warning("Error enriching @%s: %s", account.username, e)

            if i + 1 < total:
                delay = random.uniform(ENRICH_MIN_DELAY_SECONDS, ENRICH_MAX_DELAY_SECONDS)
                logger.debug("Waiting %.1fs before next profile.", delay)
                time.sleep(delay)

    def _enrich_one(self, account: Account) -> None:
        page = self._page
        url = f"{INSTAGRAM_URL}/{account.username}/"

        # Set up response interception *before* triggering the navigation so
        # we never miss the response even on a fast connection.
        try:
            with page.expect_response(
                lambda r: "web_profile_info" in r.url,
                timeout=15_000,
            ) as response_info:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            response = response_info.value
            if response.ok:
                self._apply_profile_data(account, response.json())
            else:
                logger.warning(
                    "Profile API returned HTTP %d for @%s — falling back to DOM.",
                    response.status,
                    account.username,
                )
                self._enrich_from_dom(account)
        except Exception:
            # Timeout waiting for the API response, or navigation error.
            # Try to extract what we can from the DOM.
            logger.debug(
                "web_profile_info not captured for @%s — trying DOM fallback.",
                account.username,
            )
            self._enrich_from_dom(account)

    def _apply_profile_data(self, account: Account, data: dict) -> None:
        """Parse the web_profile_info JSON and apply fields to the account."""
        try:
            user = data["data"]["user"]
        except (KeyError, TypeError):
            logger.debug("Unexpected JSON structure for @%s.", account.username)
            return

        account.biography = user.get("biography") or ""
        # Instagram uses either key depending on account type / API version.
        account.is_business = bool(
            user.get("is_business_account") or user.get("is_professional_account")
        )

        edges = (
            user.get("edge_owner_to_timeline_media", {}).get("edges") or []
        )
        if edges:
            ts = edges[0].get("node", {}).get("taken_at_timestamp")
            if ts:
                account.last_post_at = datetime.fromtimestamp(ts, tz=timezone.utc)

    def _enrich_from_dom(self, account: Account) -> None:
        """
        Fallback: extract biography from the rendered page.

        This is inherently fragile (Instagram's DOM structure changes) and
        cannot reliably recover last_post_at, so it is only a last resort.
        """
        page = self._page

        # Attempt to pull structured data from the script tags Instagram
        # embeds in the page (more stable than CSS-class-based selection).
        try:
            raw = page.evaluate(
                """() => {
                    for (const el of document.querySelectorAll('script[type="application/json"]')) {
                        const txt = el.textContent;
                        if (txt.includes('biography')) return txt;
                    }
                    return null;
                }"""
            )
            if raw:
                blob = json.loads(raw)
                # The structure varies; do a best-effort deep search.
                bio = _deep_get(blob, "biography")
                if bio is not None:
                    account.biography = bio
                is_biz = _deep_get(blob, "is_business_account") or _deep_get(
                    blob, "is_professional_account"
                )
                if is_biz is not None:
                    account.is_business = bool(is_biz)
        except Exception as e:
            logger.debug("DOM fallback failed for @%s: %s", account.username, e)

    # ------------------------------------------------------------------
    # Unfollow
    # ------------------------------------------------------------------

    def unfollow(self, username: str) -> bool:
        """
        Unfollow a single account by navigating to their profile and
        clicking the confirmation dialog.

        Returns True on success, False if the profile could not be found or
        the "Following" button was not present.
        """
        self._assert_ready()
        page = self._page
        page.goto(
            f"{INSTAGRAM_URL}/{username}/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        page.wait_for_timeout(1_500)

        # Detect a "page not available" / deleted account message.
        not_found = page.query_selector(
            'text="Sorry, this page isn\'t available."'
        )
        if not_found:
            logger.warning("Skipped @%s — page not available.", username)
            return False

        following_btn = self._find_following_button()
        if following_btn is None:
            logger.warning(
                "Skipped @%s — 'Following' button not found (not following, "
                "or page structure has changed).",
                username,
            )
            return False

        following_btn.click()

        # The confirmation dialog appears; click the "Unfollow" button in it.
        try:
            confirm_btn = page.wait_for_selector(
                'button:has-text("Unfollow")',
                timeout=6_000,
            )
            confirm_btn.click()
        except Exception:
            logger.warning(
                "Unfollow confirmation dialog did not appear for @%s.", username
            )
            return False

        # Wait for the UI to reflect the unfollowed state.
        try:
            page.wait_for_selector('button:has-text("Follow")', timeout=10_000)
        except Exception:
            # The button text sometimes differs (e.g. "Follow Back") — we
            # still consider the action successful if no error was raised.
            pass

        logger.info("Unfollowed @%s", username)
        return True

    def _find_following_button(self):
        """Return the visible 'Following' button element, or None."""
        page = self._page
        for selector in [
            'button:has-text("Following")',
            'button[aria-label="Following"]',
        ]:
            el = page.query_selector(selector)
            if el and el.is_visible():
                return el
        return None

    def unfollow_batch(
        self,
        usernames: list[str],
        dry_run: bool = False,
        progress_callback=None,
    ) -> dict[str, str]:
        """
        Unfollow a list of accounts with rate limiting.

        Identical interface to ``InstagramManager.unfollow_batch()``.

        Args:
            usernames:         List of usernames to unfollow.
            dry_run:           If True, log actions without performing them.
            progress_callback: Optional callable(username, status, index, total).

        Returns:
            Dict mapping username → status
            ("ok", "not_found", "error: …", "dry_run").
        """
        self._assert_ready()
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
            except Exception as e:
                results[username] = f"error: {e}"
                if progress_callback:
                    progress_callback(username, "error", i, total)
                logger.error("Stopping batch due to error on @%s: %s", username, e)
                break

            if (i + 1) >= total:
                continue

            if (i + 1) % BATCH_SIZE == 0:
                logger.info(
                    "Pausing %ds after %d unfollows to stay under rate limits.",
                    BATCH_PAUSE_SECONDS,
                    BATCH_SIZE,
                )
                time.sleep(BATCH_PAUSE_SECONDS)
            else:
                delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                logger.debug("Waiting %.1fs before next unfollow.", delay)
                time.sleep(delay)

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deep_get(obj, key: str):
    """
    Recursively search a nested dict/list for the first occurrence of *key*.
    Returns the value, or None if not found.
    """
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = _deep_get(v, key)
            if result is not None:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_get(item, key)
            if result is not None:
                return result
    return None
