import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yt_dlp
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


WATCHLIST_DEFAULT = [
    "MrBeast",
    "IShowSpeed",
    "KSI",
    "PewDiePie",
    "Sidemen",
    "Mark Rober",
    "Dude Perfect",
    "Logan Paul",
]
HASHTAGS_DEFAULT = [
    "#Shorts",
    "#YouTubeShorts",
    "#Viral",
]


@dataclass
class Candidate:
    video_id: str
    url: str
    title: str
    channel: str
    upload_date: str | None
    duration: int
    view_count: int
    license: str | None
    chapters: list[dict[str, Any]]


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    return [v.strip() for v in raw.split(",") if v.strip()]


def _is_reuse_safe(license_text: str | None, channel: str, allow_channels: set[str]) -> tuple[bool, str]:
    lic = (license_text or "").lower()
    ch = channel.strip().lower()
    if "creative commons" in lic:
        return True, "creative_commons_license"
    if ch in allow_channels:
        return True, "allowlisted_channel_permission"
    return False, "no_reuse_proof"


def _extract_info(url: str) -> dict[str, Any]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _search_candidates(queries: list[str], per_query: int) -> list[Candidate]:
    results: dict[str, Candidate] = {}
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for q in queries:
            info = ydl.extract_info(f"ytsearch{per_query}:{q}", download=False)
            for entry in info.get("entries", []) or []:
                if not entry:
                    continue
                duration = int(entry.get("duration") or 0)
                if duration < 75:
                    continue
                vid = entry.get("id")
                if not vid or vid in results:
                    continue
                channel = str(entry.get("channel") or "")
                candidate = Candidate(
                    video_id=vid,
                    url=entry.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}",
                    title=str(entry.get("title") or "Untitled"),
                    channel=channel,
                    upload_date=entry.get("upload_date"),
                    duration=duration,
                    view_count=int(entry.get("view_count") or 0),
                    license=entry.get("license"),
                    chapters=entry.get("chapters") or [],
                )
                results[vid] = candidate

    return list(results.values())


def _age_days(upload_date: str | None) -> float:
    if not upload_date or len(upload_date) != 8:
        return 9999.0
    try:
        dt = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 9999.0
    days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    return max(days, 1.0)


def _score(c: Candidate) -> float:
    days = _age_days(c.upload_date)
    views = max(c.view_count, 1)
    return views / math.sqrt(days)


def _choose_moment(c: Candidate) -> tuple[float, float, str]:
    target_len = 60.0
    best_start = max(0.0, min(c.duration - target_len, 30.0))
    best_reason = "default_30s_offset"

    if c.chapters:
        keywords = ["best", "crazy", "final", "win", "challenge", "reveal", "moment"]
        best_ch = None
        best_kw = -1
        for ch in c.chapters:
            title = str(ch.get("title") or "").lower()
            kw = sum(k in title for k in keywords)
            if kw > best_kw:
                best_kw = kw
                best_ch = ch
        if best_ch is not None:
            start = float(best_ch.get("start_time") or 0.0)
            best_start = max(0.0, min(c.duration - target_len, start))
            best_reason = "chapter_keyword_match"

    end = min(float(c.duration), best_start + target_len)
    if end - best_start < 58.0:
        best_start = max(0.0, end - target_len)
    return round(best_start, 2), round(best_start + target_len, 2), best_reason


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _download_video(url: str, out_dir: Path) -> Path:
    out_template = str(out_dir / "source.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f",
        "mp4/best[ext=mp4]/best",
        "-o",
        out_template,
        url,
    ]
    _run(cmd)
    matches = list(out_dir.glob("source.*"))
    if not matches:
        raise RuntimeError("Source download failed: no file generated")
    return matches[0]


def _render_vertical_short(src: Path, start: float, end: float, out_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH")
    duration = round(end - start, 2)
    vf = "crop='min(iw,ih*9/16)':ih,scale=1080:1920:flags=lanczos"
    cmd = [
        ffmpeg,
        "-y",
        "-ss",
        str(start),
        "-t",
        str(duration),
        "-i",
        str(src),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out_path),
    ]
    _run(cmd)


def _sanitize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title).strip()
    if len(t) > 85:
        t = t[:82].rstrip() + "..."
    return t


def _upload_to_youtube(video_path: Path, title: str, description: str, tags: list[str]) -> str:
    client_id = os.environ["YT_CLIENT_ID"]
    client_secret = os.environ["YT_CLIENT_SECRET"]
    refresh_token = os.environ["YT_REFRESH_TOKEN"]

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    youtube = build("youtube", "v3", credentials=creds)

    req = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "24",
            },
            "status": {
                "privacyStatus": os.getenv("YT_PRIVACY_STATUS", "public"),
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=MediaFileUpload(str(video_path), chunksize=5 * 1024 * 1024, resumable=True),
    )

    response = None
    while response is None:
        _, response = req.next_chunk()

    return f"https://www.youtube.com/watch?v={response['id']}"


def main() -> None:
    queries = _env_list("CREATOR_QUERIES", WATCHLIST_DEFAULT)
    per_query = int(os.getenv("SEARCH_RESULTS_PER_QUERY", "8"))
    allowlisted_channels = {s.strip().lower() for s in _env_list("PERMISSIONED_CHANNELS", [])}
    extra_tags = _env_list("EXTRA_HASHTAGS", HASHTAGS_DEFAULT)

    run_report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "queries": queries,
        "status": "started",
    }

    candidates = _search_candidates(queries, per_query)
    ranked = sorted(candidates, key=_score, reverse=True)

    chosen: Candidate | None = None
    rights_reason = ""
    for c in ranked:
        safe, why = _is_reuse_safe(c.license, c.channel, allowlisted_channels)
        if safe:
            chosen = c
            rights_reason = why
            break

    if not chosen:
        run_report.update(
            {
                "status": "skipped_no_safe_rights",
                "checked_candidates": len(ranked),
                "reason": "No candidate had Creative Commons license or explicit allowlisted permission.",
            }
        )
        Path("run_report.json").write_text(json.dumps(run_report, indent=2), encoding="utf-8")
        print("SKIP: no safe-reuse clip found")
        return

    start_s, end_s, reason = _choose_moment(chosen)

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        src = _download_video(chosen.url, work)
        short_path = Path("output_short.mp4")
        _render_vertical_short(src, start_s, end_s, short_path)

    short_title = _sanitize_title(f"{chosen.title} | 60s Highlight")
    desc = (
        f"60-second highlight from {chosen.channel}.\n\n"
        f"Source: {chosen.url}\n"
        f"Clip: {start_s:.2f}s-{end_s:.2f}s\n"
        f"Rights check: {rights_reason}\n\n"
        + " ".join(extra_tags)
    )
    tags = [t.lstrip("#") for t in extra_tags][:15]

    upload_url = _upload_to_youtube(short_path, short_title, desc, tags)

    run_report.update(
        {
            "status": "uploaded",
            "source_url": chosen.url,
            "source_title": chosen.title,
            "source_channel": chosen.channel,
            "source_license": chosen.license,
            "rights_gate": rights_reason,
            "clip_start_seconds": start_s,
            "clip_end_seconds": end_s,
            "moment_reason": reason,
            "title": short_title,
            "description": desc,
            "hashtags": extra_tags,
            "upload_url": upload_url,
            "copyright_claim_risk": "low_to_medium_if_rights_gate_correct",
        }
    )
    Path("run_report.json").write_text(json.dumps(run_report, indent=2), encoding="utf-8")
    print(upload_url)


if __name__ == "__main__":
    main()
