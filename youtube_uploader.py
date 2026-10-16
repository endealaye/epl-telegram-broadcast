"""
Upload broadcast news videos to YouTube (Data API v3, videos.insert).

Disabled unless YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET and
YOUTUBE_REFRESH_TOKEN are all set. Get the refresh token once with
get_youtube_refresh_token.py. Uploads default to "unlisted" (override with
YOUTUBE_PRIVACY=private|unlisted|public).
"""
import os
import random
import time

YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
VALID_PRIVACY = {"private", "unlisted", "public"}
NEWS_CATEGORY_ID = "25"  # News & Politics
DEFAULT_TAGS = ["EPL", "Premier League", "Football", "Amharic", "Ethiopia"]
MAX_UPLOAD_RETRIES = 5
RETRIABLE_STATUS = {500, 502, 503, 504}


def youtube_enabled():
    return all(
        (os.getenv(key) or "").strip()
        for key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    )


def _privacy_status():
    value = (os.getenv("YOUTUBE_PRIVACY") or "unlisted").strip().lower()
    return value if value in VALID_PRIVACY else "unlisted"


def _clean(text, limit):
    # YouTube rejects < and > in titles and descriptions.
    text = (text or "").replace("<", "").replace(">", "").strip()
    return text[:limit]


def _build_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"].strip(),
        token_uri=TOKEN_URI,
        client_id=os.environ["YOUTUBE_CLIENT_ID"].strip(),
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"].strip(),
        scopes=YOUTUBE_SCOPES,
    )
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def upload_news_video(video_path, title, description, tags=None):
    """
    Upload one mp4. Returns {"id", "url", "privacy"} or None when disabled.
    Raises on failure; callers must not let that break the Telegram broadcast.
    """
    if not youtube_enabled():
        return None

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    privacy = _privacy_status()
    body = {
        "snippet": {
            "title": _clean(title, 100) or "EPL News",
            "description": _clean(description, 4900),
            "tags": tags or DEFAULT_TAGS,
            "categoryId": NEWS_CATEGORY_ID,
            "defaultLanguage": "am",
            "defaultAudioLanguage": "am",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    youtube = _build_client()
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    retries = 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as exc:
            if exc.resp.status in RETRIABLE_STATUS and retries < MAX_UPLOAD_RETRIES:
                retries += 1
                time.sleep(random.random() * (2 ** retries))
                continue
            raise

    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"YouTube upload returned no video id: {response}")
    return {"id": video_id, "url": f"https://youtu.be/{video_id}", "privacy": privacy}
