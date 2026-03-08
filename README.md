# Daily YouTube Shorts Cloud Automation (Free)

This project runs a GitHub Actions workflow every day at **7:00 PM IST** (`13:30 UTC`) and tries to:

1. Find trending/famous creator videos from your watchlist.
2. Enforce a reuse-rights gate.
3. Create one 60-second 9:16 short clip.
4. Upload to your YouTube channel.
5. Save a run report as artifact (`run_report.json`).

## Important rights rule
This automation is intentionally strict:

- It uploads only when one of these is true:
  - Source has `Creative Commons` license.
  - Source channel is in `PERMISSIONED_CHANNELS` (channels where you have explicit written permission).
- If no safe rights are found, it **skips upload**.

This means many famous channels (including MrBeast/IShowSpeed/KSI) will usually be skipped unless permission is proven.

## One-time setup

1. Push this folder to a GitHub repository.
2. In GitHub repo: **Settings -> Secrets and variables -> Actions -> New repository secret**.
3. Add these secrets:
   - `YT_CLIENT_ID`
   - `YT_CLIENT_SECRET`
   - `YT_REFRESH_TOKEN`

## How to generate refresh token locally

Run:

```bash
python scripts/generate_refresh_token.py --client-secrets "C:\path\to\client_secrets.json"
```

It prints:

- `YT_CLIENT_ID=...`
- `YT_CLIENT_SECRET=...`
- `YT_REFRESH_TOKEN=...`

Copy those into GitHub Secrets.

## Schedule and manual run

- Daily schedule: `.github/workflows/daily_youtube_short.yml` with cron `30 13 * * *`.
- Manual test: run workflow from GitHub Actions tab with `workflow_dispatch`.

## Customize watchlist and tags

Edit these env vars in workflow file:

- `CREATOR_QUERIES`
- `EXTRA_HASHTAGS`
- `PERMISSIONED_CHANNELS`

## Outputs

- `run_report.json` artifact includes source, timestamps, upload URL, and risk status.
- `output_short.mp4` artifact exists only when clipping succeeds.
