"""drive_cache.py — Drive klasörlerini lokal cache'e indirip Path döndürür.

Cache yapısı:
    .drive_cache/
      categories/{category_id}/
        standart_images/<file>.jpg
        Text edit.docx
      parents/{parent_id}/
        raw/<file>.jpg

Pipeline `category_dir` ve `parent_dir` lokal Path bekliyor — burada bu yapıyı
mevcut klasör hiyerarşisine birebir uydurarak return ediyoruz.
"""
from pathlib import Path

import drive

ROOT = Path(__file__).parent
CACHE_ROOT = ROOT / ".drive_cache"
CATS = CACHE_ROOT / "categories"
PARENTS = CACHE_ROOT / "parents"

IMG_MIME_PREFIX = "image/"
TEXT_EDIT_BASENAME = "Text edit"
TEXT_EDIT_LOCAL = "Text edit.docx"
STANDART_IMAGES = "standart_images"
RAW = "raw"


def category_dir(category_id: str) -> Path:
    return CATS / category_id


def parent_dir(parent_id: str) -> Path:
    return PARENTS / parent_id


def _sync_image_folder(folder_id: str, dest: Path) -> list:
    dest.mkdir(parents=True, exist_ok=True)
    files = drive.list_files(folder_id, mime_filter=IMG_MIME_PREFIX)
    local_paths = []
    seen = set()
    for f in files:
        local = dest / f["name"]
        drive.download_file(f["id"], local, modified_time=f.get("modifiedTime"))
        local_paths.append(local)
        seen.add(f["name"])
    # Stale dosyaları temizle (Drive'da silinmişse cache'ten de kaldır)
    for existing in dest.iterdir():
        if existing.is_file() and existing.name not in seen:
            try:
                existing.unlink()
            except Exception:
                pass
    return local_paths


def sync_category_assets(category_id: str) -> dict:
    """standart_images/* + Text edit.docx indir. Döner: {'standart_images': [paths], 'text_edit': Path|None}."""
    cat_root = category_dir(category_id)
    standart_dest = cat_root / STANDART_IMAGES
    standart_dest.mkdir(parents=True, exist_ok=True)

    standart_meta = drive.find_child_by_name(category_id, STANDART_IMAGES, is_folder=True)
    standart_paths = []
    if standart_meta:
        standart_paths = _sync_image_folder(standart_meta["id"], standart_dest)

    # "Text edit" Google Doc olarak (uzantısız) ya da "Text edit.docx" binary olarak gelebilir.
    text_edit_meta = (drive.find_child_by_name(category_id, TEXT_EDIT_BASENAME, is_folder=False)
                      or drive.find_child_by_name(category_id, TEXT_EDIT_LOCAL, is_folder=False))
    text_edit_path = None
    if text_edit_meta:
        local = cat_root / TEXT_EDIT_LOCAL
        drive.download_file(
            text_edit_meta["id"], local,
            modified_time=text_edit_meta.get("modifiedTime"),
            mime_type=text_edit_meta.get("mimeType"),
        )
        text_edit_path = local

    return {"standart_images": standart_paths, "text_edit": text_edit_path}


def sync_parent_raw(parent_id: str) -> list:
    """parent/raw/* indir. Döner: lokal Path listesi."""
    p_root = parent_dir(parent_id)
    raw_dest = p_root / RAW
    raw_dest.mkdir(parents=True, exist_ok=True)
    raw_meta = drive.find_child_by_name(parent_id, RAW, is_folder=True)
    if not raw_meta:
        return []
    return _sync_image_folder(raw_meta["id"], raw_dest)


def clear_cache() -> None:
    """Tüm cache'i sil — Drive'da değişiklik varsa zorla yeniden indirme."""
    import shutil
    if CACHE_ROOT.exists():
        shutil.rmtree(CACHE_ROOT)
