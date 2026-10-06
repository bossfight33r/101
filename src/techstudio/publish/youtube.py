"""YouTube Data API v3: resumable upload (private + publishAt), миниатюра, субтитры. OAuth — studio auth youtube."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from techstudio.core import log
from techstudio.publish.base import PublishError

_log = log.get("youtube")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/yt-analytics-monetary.readonly",
]
CATEGORY_SCIENCE_TECH = "28"


def token_path(secrets_dir: Path, account_id: str) -> Path:
    return secrets_dir / f"{account_id}.json"


def authorize(client_secrets: Path, token: Path) -> Path:
    """Интерактивный OAuth в браузере (только на машине Босса)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    creds = flow.run_local_server(port=0)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    token.chmod(0o600)
    return token


def load_credentials(token: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not token.exists():
        raise PublishError(
            f"нет токена {token.name}: studio auth youtube --account …", retryable=False
        )
    creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _http_error(e) -> PublishError:
    status = getattr(getattr(e, "resp", None), "status", 0)
    return PublishError(
        f"YouTube API {status}: {str(e)[:300]}", retryable=status >= 500 or status == 429
    )


class YouTubePublisher:
    name = "youtube"

    def __init__(self, token: Path):
        from googleapiclient.discovery import build

        self.yt = build("youtube", "v3", credentials=load_credentials(token), cache_discovery=False)

    def upload(
        self, file: Path, *, title, description, tags, language, publish_at: datetime
    ) -> str:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags,
                "categoryId": CATEGORY_SCIENCE_TECH,
                "defaultLanguage": language,
                "defaultAudioLanguage": language,
            },
            "status": {
                "privacyStatus": "private",
                "publishAt": publish_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(
            str(file), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4"
        )
        try:
            req = self.yt.videos().insert(part="snippet,status", body=body, media_body=media)
            resp = None
            while resp is None:
                status, resp = req.next_chunk()
                if status:
                    _log.info("youtube.upload", progress=int(status.progress() * 100))
        except HttpError as e:
            raise _http_error(e) from e
        return resp["id"]

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        try:
            self.yt.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(image), mimetype="image/jpeg")
            ).execute()
        except HttpError as e:
            raise _http_error(e) from e

    def upload_captions(self, video_id: str, srt: Path, language: str, name: str) -> None:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        body = {
            "snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}
        }
        try:
            self.yt.captions().insert(
                part="snippet",
                body=body,
                media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream"),
            ).execute()
        except HttpError as e:
            raise _http_error(e) from e
