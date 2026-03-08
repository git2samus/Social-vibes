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
_LOGIN_FORM_SELECTOR = 'input[name="email"]'

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
        logger.debug("Launching Chromium with persistent profile at: %s", BROWSER_PROFILE_DIR.resolve())
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
        if self._context.pages:
            logger.debug("Reusing existing browser tab (%d tab(s) open).", len(self._context.pages))
            self._page = self._context.pages[0]
        else:
            logger.debug("No existing tabs — opening a new page.")
            self._page = self._context.new_page()
        return self

    def __exit__(self, *_) -> None:
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()

    # ------------------------------------------------------------------
    # Login / session check
    # ------------------------------------------------------------------

    def _navigate_home(self) -> bool:
        """
        Navigate to Instagram home and dismiss the profile-switcher if present.

        Returns True when the login form is visible (no active session),
        False when a session is already loaded.
        """
        page = self._page
        logger.debug("Navigating to Instagram home page.")
        page.goto(f"{INSTAGRAM_URL}/", wait_until="domcontentloaded", timeout=30_000)
        logger.debug("Home page loaded (domcontentloaded). Waiting 1.5s for React to render.")
        time.sleep(1.5)

        use_another = page.locator('div[aria-label="Use another profile"]')
        if use_another.is_visible():
            logger.debug('"Use another profile" button found — clicking it.')
            use_another.click()
            page.wait_for_load_state("domcontentloaded", timeout=30_000)
            time.sleep(1.5)

        return page.locator(_LOGIN_FORM_SELECTOR).is_visible()

    def login(self) -> None:
        """
        Navigate to Instagram and verify the session is active.

        If the saved profile already contains valid cookies the feed loads
        immediately and this method returns straight away.  If not, the
        login form will be visible in the browser window and the method
        waits (up to 2 minutes) for the user to complete it manually.
        No credentials are ever passed to this script.
        """
        needs_login = self._navigate_home()
        if needs_login:
            logger.debug("Login form detected — session cookies not present or expired.")
            print(
                "\n[Browser] Instagram login required.\n"
                "Please log in to Instagram in the browser window that just opened.\n"
                "Waiting up to 2 minutes for you to complete login..."
            )
            # Wait until Instagram makes a POST to /api/graphql (signals login success).
            with self._page.expect_request(
                lambda r: "/api/graphql" in r.url and r.method == "POST",
                timeout=120_000,
            ):
                pass
            logger.debug("POST /api/graphql detected. Waiting 2s for feed to settle.")
            # Give the feed a moment to fully settle.
            time.sleep(2)
            print("[Browser] Logged in successfully.")
        else:
            logger.debug("No login form found — reusing saved session cookies.")

        self._ready = True
        logger.info("Browser session ready.")

    def logout(self) -> None:
        """
        Log out of Instagram if an active session is detected.

        Navigates to Instagram home and checks whether the user is already
        logged in.  If so, navigates to the logout URL so the subsequent
        ``login()`` call will show the login form.  If there is no active
        session this method is a no-op.
        """
        no_session = self._navigate_home()
        if no_session:
            logger.debug("No active session — logout is a no-op.")
            print("[Browser] No active session — skipping logout.")
            return

        logger.debug("Active session detected — navigating to logout URL.")
        print("[Browser] Active session found — logging out...")
        self._page.goto(f"{INSTAGRAM_URL}/accounts/logout/", wait_until="domcontentloaded", timeout=30_000)
        time.sleep(2)

        if self._page.locator(_LOGIN_FORM_SELECTOR).is_visible():
            logger.debug("Logout successful — login form is visible.")
            print("[Browser] Logged out successfully.")
        else:
            logger.warning("Logout may not have completed — login form not detected.")
            print("[Browser] Warning: logout may not have completed.")

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
        logger.debug("Starting enrich loop for %d account(s).", total)
        for i, account in enumerate(accounts):
            if progress_callback:
                progress_callback(account.username, i, total)
            try:
                self._enrich_one(account)
            except Exception as e:
                logger.warning("Error enriching @%s: %s", account.username, e)

            if i + 1 < total:
                delay = random.uniform(ENRICH_MIN_DELAY_SECONDS, ENRICH_MAX_DELAY_SECONDS)
                logger.debug("Sleeping %.1fs before next profile (%d/%d done).", delay, i + 1, total)
                time.sleep(delay)

    def _enrich_one(self, account: Account) -> None:
        page = self._page
        url = f"{INSTAGRAM_URL}/{account.username}/"
        logger.debug("Enriching @%s — navigating to %s", account.username, url)

        # Set up response interception *before* triggering the navigation so
        # we never miss the response even on a fast connection.
        try:
            logger.debug("Setting up web_profile_info response interceptor (timeout=15s).")
            with page.expect_response(
                lambda r: "web_profile_info" in r.url,
                timeout=15_000,
            ) as response_info:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                logger.debug("Page navigation complete for @%s.", account.username)

            response = response_info.value
            logger.debug(
                "Intercepted API response for @%s: %s (HTTP %d)",
                account.username, response.url, response.status,
            )
            if response.ok:
                logger.debug("Parsing web_profile_info JSON for @%s.", account.username)
                self._apply_profile_data(account, response.json())
            else:
                logger.warning(
                    "Profile API returned HTTP %d for @%s — falling back to DOM.",
                    response.status,
                    account.username,
                )
                self._enrich_from_dom(account)
        except Exception as exc:
            # Timeout waiting for the API response, or navigation error.
            # Try to extract what we can from the DOM.
            logger.debug(
                "web_profile_info not captured for @%s (%s) — trying DOM fallback.",
                account.username, exc,
            )
            self._enrich_from_dom(account)

    def _apply_profile_data(self, account: Account, data: dict) -> None:
        """Parse the web_profile_info JSON and apply fields to the account."""
        try:
            user = data["data"]["user"]
        except (KeyError, TypeError):
            logger.debug("Unexpected JSON structure for @%s — cannot parse user node.", account.username)
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

        logger.debug(
            "Applied profile data for @%s: bio=%r is_business=%s last_post=%s",
            account.username,
            account.biography[:40] if account.biography else "",
            account.is_business,
            account.last_post_at,
        )

    def _enrich_from_dom(self, account: Account) -> None:
        """
        Fallback: extract biography from the rendered page.

        This is inherently fragile (Instagram's DOM structure changes) and
        cannot reliably recover last_post_at, so it is only a last resort.
        """
        page = self._page
        logger.debug("DOM fallback: scanning <script type=application/json> tags for @%s.", account.username)

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
                logger.debug("Found script tag containing 'biography' for @%s (%d chars). Parsing.", account.username, len(raw))
                blob = json.loads(raw)
                # The structure varies; do a best-effort deep search.
                bio = _deep_get(blob, "biography")
                if bio is not None:
                    account.biography = bio
                    logger.debug("DOM fallback: biography=%r for @%s.", bio[:40], account.username)
                is_biz = _deep_get(blob, "is_business_account") or _deep_get(
                    blob, "is_professional_account"
                )
                if is_biz is not None:
                    account.is_business = bool(is_biz)
                    logger.debug("DOM fallback: is_business=%s for @%s.", account.is_business, account.username)
            else:
                logger.debug("DOM fallback: no script tag with 'biography' found for @%s.", account.username)
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
        url = f"{INSTAGRAM_URL}/{username}/"
        logger.debug("Unfollow: navigating to %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        logger.debug("Unfollow: page loaded for @%s. Waiting 1.5s for React to render.", username)
        time.sleep(1.5)

        # Detect a "page not available" / deleted account message.
        if page.locator('text="Sorry, this page isn\'t available."').is_visible():
            logger.warning("Skipped @%s — page not available.", username)
            return False

        logger.debug("Unfollow: searching for 'Following' button on @%s profile.", username)
        following_btn = self._find_following_button()
        if following_btn is None:
            logger.warning(
                "Skipped @%s — 'Following' button not found (not following, "
                "or page structure has changed).",
                username,
            )
            return False

        logger.debug("Unfollow: clicking 'Following' button for @%s.", username)
        following_btn.click()

        # The confirmation dialog appears; click the "Unfollow" button in it.
        try:
            logger.debug("Unfollow: waiting for confirmation dialog (timeout=6s).")
            confirm_btn = page.locator('button:has-text("Unfollow")')
            confirm_btn.wait_for(timeout=6_000)
            logger.debug("Unfollow: confirmation dialog appeared. Clicking 'Unfollow'.")
            confirm_btn.click()
        except Exception as exc:
            logger.warning(
                "Unfollow confirmation dialog did not appear for @%s: %s", username, exc,
            )
            return False

        # Wait for the UI to reflect the unfollowed state.
        try:
            logger.debug("Unfollow: waiting for 'Follow' button to confirm unfollow (timeout=10s).")
            page.locator('button:has-text("Follow")').wait_for(timeout=10_000)
            logger.debug("Unfollow: 'Follow' button detected — unfollow confirmed for @%s.", username)
        except Exception:
            # The button text sometimes differs (e.g. "Follow Back") — we
            # still consider the action successful if no error was raised.
            logger.debug("Unfollow: 'Follow' button not detected for @%s (may have different label).", username)

        logger.info("Unfollowed @%s", username)
        return True

    def _find_following_button(self):
        """Return the visible 'Following' button locator, or None."""
        page = self._page
        for selector in [
            'button:has-text("Following")',
            'button[aria-label="Following"]',
        ]:
            el = page.locator(selector)
            if el.is_visible():
                logger.debug("Found 'Following' button via selector: %r", selector)
                return el
            else:
                logger.debug("Selector %r — no visible element found.", selector)
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
                logger.debug(
                    "Sleeping %.1fs before next unfollow (%d/%d done).",
                    delay, i + 1, total,
                )
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
