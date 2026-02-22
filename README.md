# Social-vibes — Instagram Following Manager

A Python CLI tool to analyse your Instagram following/followers lists and
unfollow accounts that don't follow you back.

**Data sources used:**
- **Analysis** — your Instagram data export (JSON files, no API key needed)
- **Unfollowing** — [instagrapi](https://github.com/subzeroid/instagrapi) (unofficial Instagram private API)

> **Note:** Using the unofficial API violates Instagram's Terms of Service.
> Use conservatively and at your own risk. The built-in rate limiting reduces
> (but does not eliminate) the risk of triggering bot detection.

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials (for unfollowing and `--enrich`)

Copy `.env.example` to `.env` and fill in your Instagram credentials:

```bash
cp .env.example .env
```

### 3. Get your Instagram data export

1. Go to [https://accountscenter.instagram.com/info_and_permissions/dyi/](https://accountscenter.instagram.com/info_and_permissions/dyi/)
   (**Accounts Center → Your information and permissions → Export your information**)
2. Click **Customize information** and select **Followers and following**
3. Switch the format to **JSON**, then request your download
4. Once downloaded, unzip it — you'll use that folder as `--export-dir`

---

## Usage

### Analyse your following/followers

```bash
python3 main.py analyse --export-dir ./instagram_export
```

This shows how many people you follow vs. how many follow you back, and lists
accounts that don't follow you back.

**Export to CSV:**

```bash
python3 main.py analyse --export-dir ./instagram_export --export-csv
# Writes reports/following_<timestamp>.csv and reports/non_followers_<timestamp>.csv
```

### Enrich your following list with profile data

Fetches bio, account type (personal/business), and last post date for every
account you follow. Requires Instagram credentials.

```bash
python3 main.py analyse --export-dir ./instagram_export --enrich

# Quick test on just 5 accounts
python3 main.py analyse --export-dir ./instagram_export --enrich --sample 5

# Enrich and export to CSV
python3 main.py analyse --export-dir ./instagram_export --enrich --export-csv
```

### Unfollow non-followers

```bash
# Dry run first — see what would be unfollowed
python3 main.py unfollow --export-dir ./instagram_export --dry-run

# Actually unfollow (will prompt for confirmation)
python3 main.py unfollow --export-dir ./instagram_export

# Save results to CSV
python3 main.py unfollow --export-dir ./instagram_export --export-csv
```

### Unfollow from a custom list

Create a text file with one username per line (lines starting with `#` are comments):

```
# my_unfollow_list.txt
someuser
anotheruser
```

```bash
python3 main.py unfollow --list my_unfollow_list.txt --dry-run
python3 main.py unfollow --list my_unfollow_list.txt
```

---

## Rate limiting

**Unfollowing** uses conservative delays to reduce bot-detection risk:
- **20–45 seconds** between individual unfollows (`MIN_DELAY_SECONDS`, `MAX_DELAY_SECONDS`)
- **5-minute pause** after every 10 unfollows (`BATCH_PAUSE_SECONDS`, `BATCH_SIZE`)

**Enriching** (`--enrich`) uses lighter delays for read-only profile fetches:
- **2–5 seconds** between individual profile lookups (`ENRICH_MIN_DELAY_SECONDS`, `ENRICH_MAX_DELAY_SECONDS`)

All constants can be tuned at the top of `instagram/manager.py`.

---

## Project structure

```
Social-vibes/
├── main.py                  # CLI entry point
├── requirements.txt
├── .env.example             # Credentials template
├── instagram/
│   ├── parser.py            # Parse Instagram data export JSON
│   ├── manager.py           # instagrapi login + unfollow actions
│   └── reporter.py          # CSV export and summary printing
├── .claude/
│   ├── settings.json        # Claude Code hooks configuration
│   └── hooks/
│       └── session-start.sh # Installs gh CLI on session start
└── reports/                 # Generated CSV files (git-ignored)
```