"""drive.py — Google Drive auth + folder list + upload + download."""
import io
from datetime import datetime, timezone
from pathlib import Path
import pickle

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.file",
          "https://www.googleapis.com/auth/drive.readonly"]
ROOT = Path(__file__).parent
CLIENT_SECRET_FILE = ROOT / "google_oauth_client.json"
TOKEN_FILE = ROOT / ".drive_token.pickle"


def is_configured() -> bool:
    return CLIENT_SECRET_FILE.exists()


def get_service():
    """OAuth flow — ilk seferinde browser açılır, token saklanır."""
    if not CLIENT_SECRET_FILE.exists():
        raise RuntimeError(
            f"{CLIENT_SECRET_FILE.name} bulunamadı. "
            "Google Cloud Console'dan Desktop OAuth client JSON indirip proje köküne koy."
        )
    creds = None
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_folders(parent_id: str = "root", page_size: int = 1000):
    """Drive'daki klasörleri listele (parent altındakiler) — tüm sayfalar."""
    svc = get_service()
    q = (f"'{parent_id}' in parents and "
         "mimeType = 'application/vnd.google-apps.folder' and "
         "trashed = false")
    files, token = [], None
    while True:
        res = svc.files().list(
            q=q, pageSize=page_size,
            fields="nextPageToken, files(id, name, parents)",
            orderBy="name", pageToken=token,
        ).execute()
        files.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            break
    return files


def get_folder(folder_id: str):
    svc = get_service()
    return svc.files().get(fileId=folder_id, fields="id, name, parents").execute()


def upload_file(local_path: Path, folder_id: str, name: str = None) -> dict:
    """Dosyayı verilen klasöre yükle. Aynı isimde varsa üstüne yazar."""
    svc = get_service()
    name = name or local_path.name
    q = (f"'{folder_id}' in parents and name = '{name}' and trashed = false")
    existing = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    media = MediaFileUpload(str(local_path), resumable=False)
    if existing:
        f = svc.files().update(
            fileId=existing[0]["id"], media_body=media,
            fields="id, name, webViewLink",
        ).execute()
    else:
        f = svc.files().create(
            body={"name": name, "parents": [folder_id]},
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()
    return f


def file_exists(folder_id: str, name: str) -> bool:
    """Klasörde bu isimde bir dosya var mı?"""
    svc = get_service()
    q = (f"'{folder_id}' in parents and name = '{name}' and trashed = false")
    res = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    return bool(res.get("files"))


def upload_file_strict(local_path: Path, folder_id: str, name: str = None) -> dict:
    """Yükle ama aynı isimde dosya varsa FileExistsError fırlat."""
    name = name or local_path.name
    if file_exists(folder_id, name):
        raise FileExistsError(
            f"Drive klasöründe '{name}' zaten var. Önce sil veya yeniden adlandır."
        )
    svc = get_service()
    media = MediaFileUpload(str(local_path), resumable=False)
    f = svc.files().create(
        body={"name": name, "parents": [folder_id]},
        media_body=media,
        fields="id, name, webViewLink",
    ).execute()
    return f


def list_files(parent_id: str, mime_filter: str = None, page_size: int = 1000) -> list:
    """parent_id altındaki dosyaları (folder hariç) listele — tüm sayfalar.

    mime_filter: ör. "image/" prefix match istiyorsa "image/" ver.
    Döner: [{'id', 'name', 'mimeType', 'modifiedTime'}, ...]
    """
    svc = get_service()
    q = (f"'{parent_id}' in parents and "
         "mimeType != 'application/vnd.google-apps.folder' and "
         "trashed = false")
    items, token = [], None
    while True:
        res = svc.files().list(
            q=q, pageSize=page_size,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            orderBy="name", pageToken=token,
        ).execute()
        items.extend(res.get("files", []))
        token = res.get("nextPageToken")
        if not token:
            break
    if mime_filter:
        items = [it for it in items if (it.get("mimeType") or "").startswith(mime_filter)]
    return items


def find_child_by_name(parent_id: str, name: str, is_folder: bool = None) -> dict:
    """parent altında ismi `name` olan ilk öğeyi döndür. Yoksa None.

    is_folder=True → sadece klasör; False → sadece dosya; None → fark etmez.
    """
    svc = get_service()
    safe = name.replace("'", "\\'")
    q = f"'{parent_id}' in parents and name = '{safe}' and trashed = false"
    if is_folder is True:
        q += " and mimeType = 'application/vnd.google-apps.folder'"
    elif is_folder is False:
        q += " and mimeType != 'application/vnd.google-apps.folder'"
    res = svc.files().list(
        q=q, pageSize=1,
        fields="files(id, name, mimeType, modifiedTime)",
    ).execute()
    items = res.get("files", [])
    return items[0] if items else None


# Native Google Workspace MIME → export hedef MIME
_GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document":
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet":
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation":
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _parse_drive_time(s: str) -> float:
    """Drive RFC3339 timestamp → unix timestamp."""
    if not s:
        return 0.0
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).timestamp()
    except Exception:
        return 0.0


def download_file(file_id: str, dest: Path, modified_time: str = None,
                  mime_type: str = None) -> Path:
    """Drive'dan dosya indir. modifiedTime verildiyse cache valid ise indirme atla.

    mime_type Google native ise (Docs/Sheets/Slides) export edilir (Office formatına);
    aksi halde binary indirilir.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if modified_time and dest.exists():
        remote_ts = _parse_drive_time(modified_time)
        local_ts = dest.stat().st_mtime
        if remote_ts and local_ts >= remote_ts:
            return dest

    svc = get_service()
    if mime_type and mime_type in _GOOGLE_EXPORT_MAP:
        request = svc.files().export_media(
            fileId=file_id, mimeType=_GOOGLE_EXPORT_MAP[mime_type]
        )
    else:
        request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    dest.write_bytes(buf.getvalue())
    if modified_time:
        ts = _parse_drive_time(modified_time)
        if ts:
            import os as _os
            _os.utime(dest, (ts, ts))
    return dest
