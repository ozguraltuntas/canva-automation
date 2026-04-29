"""drive.py — Google Drive auth + folder list + upload."""
from pathlib import Path
import pickle

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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


def list_folders(parent_id: str = "root", page_size: int = 100):
    """Drive'daki klasörleri listele (parent altındakiler)."""
    svc = get_service()
    q = (f"'{parent_id}' in parents and "
         "mimeType = 'application/vnd.google-apps.folder' and "
         "trashed = false")
    res = svc.files().list(
        q=q, pageSize=page_size,
        fields="files(id, name, parents)",
        orderBy="name",
    ).execute()
    return res.get("files", [])


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
