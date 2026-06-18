"""config.py — app_config.json read/write helpers (persisted user settings)."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "app_config.json"

DEFAULTS = {
    "brand_folder_id": "",
    "brand_folder_name": "",
    "llm_provider": "gemini",
    "last_category_id": "",
    "last_category_name": "",
    "last_parent_id": "",
    "last_parent_name": "",
    "last_child_id": "",
    "last_child_name": "",
    "last_drive_folder_id": "",
    "last_drive_folder_name": "",
}


def load() -> dict:
    if not CONFIG_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except Exception:
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def save(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def get(key: str, default=None):
    cfg = load()
    return cfg.get(key, default if default is not None else DEFAULTS.get(key))


def set_value(key: str, value) -> None:
    cfg = load()
    cfg[key] = value
    save(cfg)


def set_many(updates: dict) -> None:
    cfg = load()
    cfg.update(updates)
    save(cfg)
