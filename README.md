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
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials (for unfollowing only)

Copy `.env.example` to `.env` and fill in your Instagram credentials:

```bash
cp .env.example .env
```

### 3. Get your Instagram data export

1. Open Instagram → **Settings** → **Your activity** → **Download your information**
2. Select **JSON** format, request your data
3. Once downloaded, unzip it — you'll use that folder as `--export-dir`

---

## Usage

### Analyse your following/followers

```bash
python main.py analyse --export-dir ./instagram_export
```

This shows how many people you follow vs. how many follow you back, and lists
accounts that don't follow you back.

**Export to CSV:**

```bash
python main.py analyse --export-dir ./instagram_export --export-csv
# Writes reports/following_<timestamp>.csv and reports/non_followers_<timestamp>.csv
```

### Unfollow non-followers

```bash
# Dry run first — see what would be unfollowed
python main.py unfollow --export-dir ./instagram_export --dry-run

# Actually unfollow (will prompt for confirmation)
python main.py unfollow --export-dir ./instagram_export

# Save results to CSV
python main.py unfollow --export-dir ./instagram_export --export-csv
```

### Unfollow from a custom list

Create a text file with one username per line (lines starting with `#` are comments):

```
# my_unfollow_list.txt
someuser
anotheruser
```

```bash
python main.py unfollow --list my_unfollow_list.txt --dry-run
python main.py unfollow --list my_unfollow_list.txt
```

---

## Rate limiting

The unfollow command uses conservative delays between requests:
- **20–45 seconds** between individual unfollows
- **5-minute pause** after every 10 unfollows

These can be tuned in `instagram/manager.py` (`MIN_DELAY_SECONDS`, `MAX_DELAY_SECONDS`,
`BATCH_SIZE`, `BATCH_PAUSE_SECONDS`).

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
└── reports/                 # Generated CSV files (git-ignored)
```