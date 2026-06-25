"""app.py — Streamlit GUI (3 tab: Araç Görseli / Content / Ayarlar).

Drive üzerinden çalışır: brand_folder → category → parent → child Drive
klasörleri. Resimler ve Text edit.docx Drive API ile indirilir, .drive_cache/'e
yazılır, sonra LLM'e gönderilir.

Çalıştırma: .venv/bin/streamlit run app.py
"""
import os
import re
import time
from pathlib import Path

import streamlit as st

import streamlit.elements.image as _stl_img
if not hasattr(_stl_img, "image_to_url"):
    from streamlit.elements.lib.image_utils import image_to_url as _new_image_to_url
    from streamlit.elements.lib.layout_utils import LayoutConfig as _StlLayoutConfig

    def _image_to_url_shim(image, width, clamp, channels, output_format, image_id):
        return _new_image_to_url(
            image, _StlLayoutConfig(width=width), clamp, channels, output_format, image_id
        )

    _stl_img.image_to_url = _image_to_url_shim

from PIL import Image
from streamlit_drawable_canvas import st_canvas
from dotenv import load_dotenv

import pipeline
import drive
import auto_mask
import config
import content_pipeline
import drive_cache

load_dotenv()

ROOT = Path(__file__).parent
INPUTS = ROOT / "inputs"
MASKS = ROOT / "masks"
TEMPLATES = ROOT / "templates"
OUTPUTS = ROOT / "outputs"
PROMPT_FILE = ROOT / "content_prompt.md"
for d in (INPUTS, MASKS, OUTPUTS):
    d.mkdir(exist_ok=True)

DEFAULT_TEMPLATE = TEMPLATES / "mountain.png"
MAX_DISPLAY = 900
DRIVE_UPLOAD_NAME = "5.jpg"

st.set_page_config(page_title="Canva Otomasyon", layout="wide")

ss = st.session_state
ss.setdefault("uploaded_path", None)
ss.setdefault("uploaded_name", None)
ss.setdefault("mask_path", None)
ss.setdefault("output_path", None)
ss.setdefault("ai_drawing", None)
ss.setdefault("canvas_key_seed", 0)

# Content tab — selections + cache state
ss.setdefault("content_result", None)
ss.setdefault("content_edit_title", "")
ss.setdefault("content_edit_bullets", "")
ss.setdefault("content_edit_description", "")

cfg = config.load()


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text()
    return ""


@st.cache_data(ttl=60, show_spinner=False)
def cached_list_folders(parent_id: str):
    return drive.list_folders(parent_id)


@st.cache_data(ttl=60, show_spinner=False)
def cached_sync_parent_raw(parent_id: str):
    """Aynı parent için raw/ klasörünü tek seferlik Drive'dan sync et."""
    return drive_cache.sync_parent_raw(parent_id)


@st.cache_data(ttl=60, show_spinner=False)
def cached_sync_category_assets(category_id: str):
    """Aynı category için standart_images + Text edit'i tek seferlik sync et."""
    return drive_cache.sync_category_assets(category_id)


def render_drive_folder_browser(state_prefix: str, on_select_label: str,
                                 on_select_callback) -> None:
    """Reusable Drive folder browser UI. State is keyed under ss with state_prefix.

    Kullanım: 📁 ile başlayan butonlar **klasörün İÇİNE GİRER**. Yeşil ✓ butonu
    şu an görüntülenen klasörü **SEÇER**.
    """
    bc_key = f"{state_prefix}_breadcrumb"
    parent_key = f"{state_prefix}_browse_parent"
    if bc_key not in ss:
        ss[bc_key] = [("root", "My Drive")]
    if parent_key not in ss:
        ss[parent_key] = "root"

    cur_name = ss[bc_key][-1][1]
    breadcrumb_str = " / ".join(name for _, name in ss[bc_key])
    st.markdown(f"**Şu an:** `{breadcrumb_str}`")
    st.caption(
        "📁 ile başlayan klasör butonuna tıklayarak içine gir. "
        "Aradığın klasördeyken aşağıdaki **yeşil ✓ butonuna** bas — o klasör seçilir."
    )

    col_back, col_select = st.columns([1, 3])
    with col_back:
        can_go_up = len(ss[bc_key]) > 1
        if st.button("⬆ Üst klasör", key=f"{state_prefix}_back", disabled=not can_go_up):
            ss[bc_key] = ss[bc_key][:-1]
            ss[parent_key] = ss[bc_key][-1][0]
            st.rerun()
    with col_select:
        at_root = ss[parent_key] == "root"
        if st.button(
            f"✅ {on_select_label} → **{cur_name}**",
            key=f"{state_prefix}_set",
            type="primary",
            disabled=at_root,
            use_container_width=True,
        ):
            on_select_callback(ss[parent_key], cur_name)
            st.rerun()
        if at_root:
            st.caption("⚠️ My Drive kökünü seçemezsin — bir alt klasöre gir.")

    st.markdown("**Bu klasör altındaki alt klasörler:**")
    folders = cached_list_folders(ss[parent_key])
    if folders:
        cols = st.columns(min(len(folders), 4))
        for i, f in enumerate(folders):
            col = cols[i % len(cols)]
            if col.button(f"📁 {f['name']}", key=f"{state_prefix}_f_{f['id']}"):
                ss[bc_key].append((f["id"], f["name"]))
                ss[parent_key] = f["id"]
                st.rerun()
    else:
        st.caption("(Bu klasörde alt klasör yok — burayı seçmek istiyorsan yukarıdaki yeşil butona bas)")


tab_vehicle, tab_content, tab_settings = st.tabs(
    ["🚗 Araç Görseli", "📝 Content.docx", "⚙️ Ayarlar"]
)


# =============================================================================
# TAB 1 — ARAÇ GÖRSELİ
# =============================================================================
def render_vehicle_tab():
    st.title("Araç Görsel Üretici")

    _render_brand_picker("v")

    st.header("1. Araç fotoğrafı")

    def _set_uploaded(path: Path, name: str):
        ss.uploaded_path = path
        ss.uploaded_name = name
        candidate = MASKS / f"{path.stem}.mask.png"
        ss.mask_path = candidate if candidate.exists() else None
        ss.ai_drawing = None
        ss.canvas_key_seed += 1

    uploaded = st.file_uploader(
        "Resim seç (jpg/png)", type=["jpg", "jpeg", "png"], key="file_uploader"
    )
    if uploaded is not None and ss.uploaded_name != uploaded.name:
        target = INPUTS / uploaded.name
        with open(target, "wb") as f:
            f.write(uploaded.getbuffer())
        _set_uploaded(target, uploaded.name)
        st.rerun()

    if not ss.uploaded_path:
        st.info("Devam etmek için bir araç fotoğrafı yükle.")
        return

    img_path = Path(ss.uploaded_path)
    img = Image.open(img_path).convert("RGB")
    st.success(f"Yüklendi: **{ss.uploaded_name}** ({img.size[0]}×{img.size[1]})")

    st.header("2. Mask — silinecek bölgeler")
    st.caption(
        "Plaka için **çizmen gerekmiyor** (PhotoRoom otomatik silecek). "
        "Sadece **2 jant ortasındaki marka logosu** + **ön/arka amblem** = toplam 3 nokta üstüne kırmızı boya."
    )

    scale = min(MAX_DISPLAY / img.width, MAX_DISPLAY / img.height, 1.0)
    disp_w, disp_h = int(img.width * scale), int(img.height * scale)
    disp_img = img.resize((disp_w, disp_h), Image.LANCZOS)

    col_a, col_b = st.columns([3, 1])
    with col_b:
        brush = st.slider("Fırça (px, ekran ölçeği)", 5, 80, 25)
        drawing_mode = st.radio(
            "Mod", ["circle", "freedraw", "transform"],
            format_func=lambda m: {
                "circle": "🔴 Daire çiz",
                "freedraw": "✏️ Boya",
                "transform": "↔️ Taşı/Boyutlandır",
            }[m],
            horizontal=False,
        )
        if auto_mask.is_available():
            if st.button("🎯 AI ile otomatik mask", use_container_width=True):
                with st.spinner("GroundingDINO çalışıyor (~5-10 sn)..."):
                    try:
                        circles = auto_mask.auto_mask_circles(img_path)
                        if not circles:
                            st.warning("AI bir şey bulamadı — manuel çiz.")
                        else:
                            objects = []
                            for cx, cy, r in circles:
                                objects.append({
                                    "type": "circle",
                                    "left": (cx - r) * scale,
                                    "top": (cy - r) * scale,
                                    "radius": r * scale,
                                    "fill": "rgba(255, 0, 0, 0.45)",
                                    "stroke": "rgba(255, 0, 0, 0.0)",
                                    "strokeWidth": 0,
                                    "originX": "left",
                                    "originY": "top",
                                })
                            ss.ai_drawing = {"version": "4.4.0", "objects": objects}
                            ss.canvas_key_seed += 1
                            st.rerun()
                    except Exception as e:
                        st.error(f"AI auto-mask hatası: {e}")
        else:
            st.info("🔒 AI auto-mask için Replicate token gerekli — `.env`'e `REPLICATE_API_TOKEN=r8_...` ekle.")
        if st.button("🗑 Mask'ı sıfırla", use_container_width=True):
            ss.ai_drawing = None
            ss.canvas_key_seed += 1
            st.rerun()

    with col_a:
        canvas_result = st_canvas(
            fill_color="rgba(255, 0, 0, 0.45)",
            stroke_color="rgba(255, 0, 0, 0.7)",
            stroke_width=brush,
            background_image=disp_img,
            width=disp_w,
            height=disp_h,
            drawing_mode=drawing_mode,
            initial_drawing=ss.ai_drawing,
            key=f"canvas_{img_path.name}_{ss.canvas_key_seed}",
        )

    if canvas_result.image_data is not None:
        import numpy as np
        arr = canvas_result.image_data
        alpha = arr[:, :, 3]
        if alpha.max() > 0:
            mask_disp = Image.fromarray(alpha).convert("L")
            mask_full = mask_disp.resize(img.size, Image.NEAREST)
            mask_full = mask_full.point(lambda p: 255 if p > 30 else 0)
            mp = MASKS / f"{img_path.stem}.mask.png"
            mask_full.save(mp)
            ss.mask_path = mp

    if ss.mask_path and Path(ss.mask_path).exists():
        nz = sum(1 for p in Image.open(ss.mask_path).getdata() if p > 0)
        st.success(f"Mask hazır: {nz:,} pixel boyalı")
    else:
        st.warning("Henüz mask yok. Yukarıdaki resmin üstüne çizmeye başla.")

    st.header("3. Metinler (alt banner)")
    combined = st.text_input(
        "Araç bilgisi (model + yıl veya yıl aralığı)",
        value="BMW I5 SERIES G60 2024-2028",
        placeholder="örn: Acura ADX 2025-2029  •  Chevrolet Suburban 2007",
    )
    _range = re.search(r'\b(\d{4}\s*[-–]\s*\d{2,4})\b', combined)
    if _range:
        years = _range.group(1).replace(' ', '')
        title = combined[:_range.start()].strip().rstrip(',').rstrip()
    else:
        # Aralık yoksa tek yıl-benzeri token'a (19xx/20xx) düş — en sağdakini al
        _singles = list(re.finditer(r'\b((?:19|20)\d{2})\b', combined))
        if _singles:
            m = _singles[-1]
            years = m.group(1)
            title = combined[:m.start()].strip().rstrip(',').rstrip()
        else:
            years = ""
            title = combined.strip()
    st.caption(f"📌 Title: **{title or '(boş)'}**  |  Years: **{years or '(yıl bulunamadı)'}**")

    st.header("4. Drive hedef klasörü")
    target_id, target_name = _render_drive_hierarchy_picker("v")

    st.header("5. İşle")
    ready = (
        ss.uploaded_path
        and ss.mask_path and Path(ss.mask_path).exists()
        and title.strip()
        and years.strip()
    )
    if not ready:
        st.warning("Foto + mask + title + years gerekli.")

    if st.button("🚀 İşle ve üret", type="primary", disabled=not ready):
        with st.spinner("Pipeline çalışıyor (~15-20 sn)..."):
            try:
                t0 = time.time()
                output_path = OUTPUTS / f"{img_path.stem}_{years}.jpg"
                pipeline.process_one(
                    input_image=img_path,
                    mask=Path(ss.mask_path),
                    template=DEFAULT_TEMPLATE,
                    title=title.strip(),
                    years=years.strip(),
                    output=output_path,
                    width_ratio=0.5256,
                )
                ss.output_path = output_path
                dt = time.time() - t0
                st.success(f"Üretildi: **{output_path.name}** ({dt:.1f} sn)")

                if target_id and drive.is_configured():
                    with st.spinner(f"Drive'a yükleniyor ({DRIVE_UPLOAD_NAME})..."):
                        try:
                            info = drive.upload_file_strict(
                                output_path, target_id, name=DRIVE_UPLOAD_NAME
                            )
                            link = info.get("webViewLink")
                            st.success(f"Drive'a yüklendi: **{info['name']}** ({target_name})")
                            if link:
                                st.markdown(f"🔗 [Drive'da aç]({link})")
                        except FileExistsError as fe:
                            st.error(
                                f"⚠️ {fe} — Drive klasöründe **{DRIVE_UPLOAD_NAME}** zaten var, yüklenmedi."
                            )
            except Exception as e:
                st.exception(e)

    if ss.output_path and Path(ss.output_path).exists():
        st.header("6. Sonuç")
        st.image(str(ss.output_path), caption=Path(ss.output_path).name)
        with open(ss.output_path, "rb") as f:
            st.download_button(
                "⬇ İndir", f, file_name=Path(ss.output_path).name, mime="image/jpeg"
            )


# =============================================================================
# TAB 2 — CONTENT.DOCX
# =============================================================================
def _select_dropdown_with_id(label: str, items: list, current_id: str,
                              key: str) -> dict:
    """Editable combobox: text_input (sol, geniş) + listeden-seç selectbox (sağ, dar).

    Text input gerçek HTML <input> — browser'ın tüm native özellikleri çalışır:
    mouse ile text seç, Cmd+C/Cmd+V/Cmd+A, Backspace, sağ tık → paste menüsü.

    Listeden seç dropdown değişince on_change callback ile text input'a kopyalanır.
    Text input geçerli bir isimse → o öğe döner. Değilse → fuzzy öneriler gösterilir,
    None döner.
    """
    if not items:
        return None
    names = [it["name"] for it in items]
    text_key = f"{key}_text"
    sel_key = f"{key}_sel"
    sig_key = f"{key}__items_sig"

    default_name = next((it["name"] for it in items if it["id"] == current_id),
                        names[0])

    # Items listesi değişti mi (parent değişti → children listesi yenilendi)
    sig = tuple(it["id"] for it in items)
    if ss.get(sig_key) != sig:
        ss[sig_key] = sig
        ss[text_key] = default_name
        ss.pop(sel_key, None)

    # İlk render: text input boşsa default'a setle
    if text_key not in ss:
        ss[text_key] = default_name

    # Text input → selectbox sync: kullanıcı text input'a geçerli bir değer
    # yapıştırdığında, expander içindeki selectbox da o değere senkronize olsun.
    # (Streamlit key'li widget'ta session state index'e tercih edildiği için bu
    # şart — yoksa selectbox eski seçili değeri göstermeye devam eder.)
    cur_text = ss.get(text_key, "")
    if cur_text in names and ss.get(sel_key) != cur_text:
        ss[sel_key] = cur_text

    def _sync_from_select():
        ss[text_key] = ss[sel_key]

    st.text_input(label, key=text_key,
                   placeholder="Yaz, kopyala, yapıştır")

    with st.expander(f"📋 Listeden seç ({len(items)} öğe)", expanded=False):
        sel_idx = names.index(ss.get(text_key, default_name)) \
            if ss.get(text_key) in names else 0
        st.selectbox("Liste", names, index=sel_idx, key=sel_key,
                      on_change=_sync_from_select, label_visibility="collapsed")

    val = (ss.get(text_key) or "").strip()
    if val in names:
        return next(it for it in items if it["name"] == val)
    if val:
        val_l = val.lower()
        sugg = [it for it in items if val_l in it["name"].lower()]
        if sugg:
            st.caption(f"💡 {', '.join(s['name'] for s in sugg[:5])}")
    return None


def _render_brand_picker(prefix: str) -> str:
    """Brand klasörü seçici — Vehicle ve Content tab'larının üstünde görünür.

    Returns brand_folder_id (boş string olabilir — picker hâlâ açıksa).
    State: ss[f"{prefix}_show_brand_picker"] — picker açık/kapalı toggle.
    """
    cur = config.load()
    brand_id = cur.get("brand_folder_id", "")
    brand_name = cur.get("brand_folder_name", "")
    show_key = f"{prefix}_show_brand_picker"

    # Brand setli değilse picker'ı varsayılan açık göster
    if not brand_id and show_key not in ss:
        ss[show_key] = True

    # Compact view: brand setli + picker kapalı
    if brand_id and not ss.get(show_key, False):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.success(f"🏷️ Brand: **{brand_name}**")
        with col2:
            if st.button("🔄 değiştir", key=f"{prefix}_change_brand"):
                ss[show_key] = True
                st.rerun()
        return brand_id

    # Picker açık
    if not drive.is_configured():
        st.error("Drive yapılandırılmamış — `google_oauth_client.json` proje köküne koy.")
        return brand_id

    def _on_brand_select(fid: str, fname: str):
        config.set_many({
            "brand_folder_id": fid, "brand_folder_name": fname,
            "last_category_id": "", "last_category_name": "",
            "last_parent_id": "", "last_parent_name": "",
            "last_child_id": "", "last_child_name": "",
        })
        ss[show_key] = False
        cached_list_folders.clear()

    if brand_id:
        st.caption(f"🏷️ Şu anki brand: **{brand_name}** — yenisini seç ya da iptal et")
        if st.button("✕ İptal — mevcut brand kalsın", key=f"{prefix}_cancel_brand"):
            ss[show_key] = False
            st.rerun()
    else:
        st.info("Bir brand klasörü seç. Bu klasörün altında kategoriler "
                "(wiper blade, rear wiper blade...) olmalı.")

    with st.expander("🔍 Drive'dan brand klasörünü seç", expanded=True):
        render_drive_folder_browser(f"{prefix}_brand", "Brand olarak ayarla", _on_brand_select)

    return brand_id


def _render_drive_hierarchy_picker(prefix: str) -> tuple:
    """Brand → Category → Parent → Child hiyerarşisini editable comboboxlar ile göster.

    Returns (target_id, target_name) where target = selected child folder.
    Boş seçim varsa (None, "(seçilmedi)") döner.

    Content tab ve Vehicle tab arasında aynı `last_*` config alanları paylaşılıyor —
    bir tab'taki seçim diğerine de yansır.
    """
    if not drive.is_configured():
        st.warning("Drive yapılandırılmamış — sadece lokale kaydedilecek.")
        return None, "(seçilmedi)"

    cur_cfg = config.load()
    if not cur_cfg.get("brand_folder_id"):
        # Brand picker zaten sayfanın üstünde görünür — burada sessizce çık.
        return None, "(seçilmedi)"

    try:
        cats_all = cached_list_folders(cur_cfg["brand_folder_id"])
    except Exception as e:
        st.error(f"Drive listesi alınamadı: {e}")
        return None, "(seçilmedi)"

    categories = [c for c in cats_all
                  if c["name"].lower() not in ("standart_images", "miscellanious", "miscellaneous")]
    if not categories:
        st.error("Brand klasöründe kategori yok.")
        return None, "(seçilmedi)"

    category = _select_dropdown_with_id(
        "Category", categories, cur_cfg.get("last_category_id", ""), f"{prefix}_category"
    )
    if category and (category["id"] != cur_cfg.get("last_category_id")):
        config.set_many({
            "last_category_id": category["id"], "last_category_name": category["name"],
            "last_parent_id": "", "last_parent_name": "",
            "last_child_id": "", "last_child_name": "",
        })
        cur_cfg = config.load()
    if not category:
        return None, "(seçilmedi)"

    parents_all = cached_list_folders(category["id"])
    parents = [p for p in parents_all if p["name"] != "standart_images"]
    if not parents:
        st.error("Bu kategoride parent klasör yok.")
        return None, "(seçilmedi)"

    parent = _select_dropdown_with_id(
        "Parent (model)", parents, cur_cfg.get("last_parent_id", ""), f"{prefix}_parent"
    )
    if parent and (parent["id"] != cur_cfg.get("last_parent_id")):
        config.set_many({
            "last_parent_id": parent["id"], "last_parent_name": parent["name"],
            "last_child_id": "", "last_child_name": "",
        })
        cur_cfg = config.load()
    if not parent:
        return None, "(seçilmedi)"

    children_all = cached_list_folders(parent["id"])
    children = [c for c in children_all if c["name"] != "raw"]
    if not children:
        st.error(f"Parent'ta child yok: {parent['name']}")
        return None, "(seçilmedi)"

    child = _select_dropdown_with_id(
        "Child (part_number)", children, cur_cfg.get("last_child_id", ""), f"{prefix}_child"
    )
    if child and (child["id"] != cur_cfg.get("last_child_id")):
        config.set_many({"last_child_id": child["id"], "last_child_name": child["name"]})
    if not child:
        return None, "(seçilmedi)"

    st.success(f"📂 Hedef: **{child['name']}** (5.jpg buraya yüklenecek)")
    return child["id"], child["name"]


def render_content_tab():
    st.title("Content.docx Üretici")

    if not drive.is_configured():
        st.error("Drive yapılandırılmamış — `google_oauth_client.json` proje köküne koy.")
        return

    brand_folder_id = _render_brand_picker("c")
    if not brand_folder_id:
        return

    cur = config.load()
    brand_folder_name = cur.get("brand_folder_name", "")

    # 1. Category — directly from brand_folder children
    try:
        cats_all = cached_list_folders(brand_folder_id)
    except Exception as e:
        st.error(f"Drive listesi alınamadı: {e}")
        return
    categories = [c for c in cats_all
                  if c["name"].lower() not in ("standart_images", "miscellanious", "miscellaneous")]
    if not categories:
        st.error(f"Brand klasöründe kategori yok: {brand_folder_name}")
        return
    category = _select_dropdown_with_id("Category", categories, cur.get("last_category_id", ""), "c_category")
    if category and (category["id"] != cur.get("last_category_id")):
        config.set_many({"last_category_id": category["id"], "last_category_name": category["name"],
                         "last_parent_id": "", "last_parent_name": "",
                         "last_child_id": "", "last_child_name": ""})
        cur = config.load()
    if not category:
        st.info("Geçerli bir kategori seç (yukarıdaki listeden).")
        return

    # 3. Sync category assets (standart_images + Text edit.docx)
    with st.spinner("Drive: standart_images & Text edit.docx indiriliyor..."):
        try:
            assets = cached_sync_category_assets(category["id"])
        except Exception as e:
            st.error(f"Drive'dan indirme hatası: {e}")
            return

    col_si, col_te = st.columns(2)
    with col_si:
        st.subheader("standart_images/")
        si_imgs = assets["standart_images"]
        if si_imgs:
            cols = st.columns(min(len(si_imgs), 4))
            for i, p in enumerate(si_imgs):
                cols[i % len(cols)].image(str(p), caption=p.name, use_container_width=True)
        else:
            st.caption("(Drive'da bu kategori altında standart_images bulunamadı veya boş)")

    with col_te:
        st.subheader("Text edit.docx")
        te_path = assets["text_edit"]
        if te_path and te_path.exists():
            try:
                text_content = content_pipeline.read_text_edit_docx(te_path)
            except Exception as e:
                st.error(f"docx okunamadı: {e}")
                text_content = ""
            lines = text_content.splitlines()
            preview = "\n".join(lines[:2])
            st.text(preview if preview else "(boş)")
            if len(lines) > 2:
                with st.expander("Show more"):
                    st.text(text_content)
        else:
            st.caption("Text edit.docx bulunamadı")

    # 4. Parent
    parents_all = cached_list_folders(category["id"])
    parents = [p for p in parents_all if p["name"] != "standart_images"]
    if not parents:
        st.error("Bu kategoride parent klasör yok.")
        return
    parent = _select_dropdown_with_id("Parent (model)", parents, cur.get("last_parent_id", ""), "c_parent")
    if parent and (parent["id"] != cur.get("last_parent_id")):
        config.set_many({"last_parent_id": parent["id"], "last_parent_name": parent["name"],
                         "last_child_id": "", "last_child_name": ""})
        cur = config.load()
    if not parent:
        st.info("Geçerli bir parent (model) seç.")
        return

    # 5. Child
    children_all = cached_list_folders(parent["id"])
    children = [c for c in children_all if c["name"] != "raw"]
    if not children:
        st.error(f"Parent'ta child (part_number) yok: {parent['name']}")
        return
    child = _select_dropdown_with_id("Child (part_number)", children, cur.get("last_child_id", ""), "c_child")
    if child and (child["id"] != cur.get("last_child_id")):
        config.set_many({"last_child_id": child["id"], "last_child_name": child["name"]})
        cur = config.load()
    if not child:
        st.info("Geçerli bir child (part_number) seç.")
        return

    # 6. Sync parent raw/
    with st.spinner("Drive: raw/ indiriliyor..."):
        try:
            raw_paths = cached_sync_parent_raw(parent["id"])
        except Exception as e:
            st.error(f"raw/ indirme hatası: {e}")
            raw_paths = []

    st.subheader("raw/")
    if raw_paths:
        cols = st.columns(min(len(raw_paths), 4))
        for i, p in enumerate(raw_paths):
            cols[i % len(cols)].image(str(p), caption=p.name, use_container_width=True)
    else:
        st.caption("(raw/ klasörü yok veya boş)")

    # 7. Inputs + result — fragment'e taşındı, böylece text/checkbox/button etkileşimleri
    # üstteki standart_images & raw thumbnails'i yeniden render etmiyor.
    _render_content_io_fragment(category, parent, child, cur)


@st.fragment
def _render_content_io_fragment(category, parent, child, cur):
    """Notlar/OEM/Üret/Sonuç/Kaydet — fragment olduğu için bu blok içindeki
    widget etkileşimleri sadece bu bloğu rerun eder, üstteki görselleri değil."""
    st.subheader("Ürüne özel notlar")
    user_text = st.text_area("Notlar", "", height=100, key="c_user_text",
                             placeholder="Bu ürüne özel notlar — title bilgisi, ekstra detaylar...")

    st.subheader("OEM kod(lar)")
    oem = st.text_input("OEM", "", key="c_oem", placeholder="örn: A2518200845  A1234567890")
    oem_in_title = st.checkbox("Title sonuna ekle", key="c_oem_title")

    provider = cur.get("llm_provider", "gemini")
    provider_options = {
        "gemini": "Gemini (gemini-2.5-flash)",
        "claude": "Claude (claude-opus-4-7)",
        "openai": "OpenAI (gpt-5.5)",
        "minimax": "MiniMax (MiniMax-M2.7)",
    }
    provider_label = provider_options.get(provider, provider)

    st.markdown("---")
    st.caption(f"🤖 LLM: **{provider_label}** — değiştirmek için ⚙️ Ayarlar")
    if st.button("🚀 Content.docx üret", type="primary", key="c_generate"):
        # Drive ön-kontrol: hedef klasörde zaten Content.docx varsa LLM'i çağırma
        blocked = False
        if drive.is_configured() and child:
            try:
                if drive.file_exists(child["id"], "Content.docx"):
                    st.error(
                        f"⚠️ **{child['name']}/Content.docx** Drive'da zaten var. "
                        "LLM çağrılmadı (boşa para harcamamak için). "
                        "Önce Drive'dan sil veya yeniden adlandır, sonra tekrar üret."
                    )
                    blocked = True
            except Exception as e:
                st.warning(f"Drive ön-kontrol yapılamadı (devam ediliyor): {e}")

        prompt_text = load_prompt() if not blocked else ""
        if blocked:
            pass
        elif not prompt_text.strip():
            st.error("content_prompt.md boş veya yok.")
        else:
            api_key_map = {
                "claude": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "gemini": "GEMINI_API_KEY",
                "minimax": "MINIMAX_API_KEY",
            }
            api_key_var = api_key_map.get(provider, "ANTHROPIC_API_KEY")
            if not os.getenv(api_key_var):
                st.error(f"`.env` dosyasında **{api_key_var}** tanımlı değil.")
            else:
                oem_targets = []
                if oem_in_title:
                    oem_targets.append("title")
                with st.spinner(f"{provider_options[provider]} çağrılıyor..."):
                    try:
                        t0 = time.time()
                        result = content_pipeline.generate_content(
                            provider=provider,
                            category_dir=drive_cache.category_dir(category["id"]),
                            parent_dir=drive_cache.parent_dir(parent["id"]),
                            user_text=user_text,
                            oem=oem,
                            oem_targets=oem_targets,
                            prompt_text=prompt_text,
                        )
                        dt = time.time() - t0
                        ss.content_result = result
                        ss.content_edit_title = result.get("title", "")
                        ss.content_edit_bullets = result.get("bullets", "")
                        ss.content_edit_description = result.get("description", "")
                        st.success(
                            f"Üretildi ({dt:.1f} sn, {result['image_count']} görsel gönderildi)"
                        )
                    except RuntimeError as e:
                        # LLM returned empty / blocked / malformed response — show red error
                        # with raw output (if any) so user can diagnose.
                        st.error(f"❌ {e}")
                        raw = getattr(e, "raw_output", "") or ""
                        if raw.strip():
                            with st.expander("LLM ham çıktısı (debug)", expanded=False):
                                st.code(raw, language=None)
                        else:
                            st.caption("LLM hiç metin döndürmedi (ham çıktı boş).")
                        # Clear previous result so stale text_area'lar görünmesin
                        ss.content_result = None
                    except Exception as e:
                        st.exception(e)

    if ss.content_result:
        st.markdown("---")
        st.subheader("Sonuç (edit edebilirsin)")

        for w in ss.content_result.get("warnings", []):
            st.error(f"⚠️ {w}")

        ss.content_edit_title = st.text_area(
            f"TITLE  ({len(ss.content_edit_title)}/200)",
            ss.content_edit_title, height=70, key="c_e_title",
        )
        ss.content_edit_bullets = st.text_area(
            "BULLET POINTS", ss.content_edit_bullets, height=200, key="c_e_bullets",
        )
        ss.content_edit_description = st.text_area(
            "DESCRIPTION", ss.content_edit_description, height=200, key="c_e_desc",
        )

        with st.expander("LLM ham çıktısı (debug)"):
            st.code(ss.content_result.get("raw", ""), language=None)

        st.markdown("---")
        st.subheader(f"Hedef: {child['name']}/Content.docx")
        if st.button("💾 Content.docx kaydet & Drive'a yükle", type="primary", key="c_save"):
            edited = {
                "title": ss.content_edit_title.strip(),
                "bullets": ss.content_edit_bullets.strip(),
                "description": ss.content_edit_description.strip(),
            }
            local_out = OUTPUTS / f"Content_{child['id']}.docx"
            try:
                content_pipeline.save_content_docx(edited, local_out)
                st.success(f"Lokale kaydedildi: `{local_out.name}`")
            except Exception as e:
                st.exception(e)
                return

            with st.spinner("Drive'a yükleniyor..."):
                try:
                    info = drive.upload_file_strict(
                        local_out, child["id"], name="Content.docx"
                    )
                    link = info.get("webViewLink")
                    st.success(f"Drive'a yüklendi: **{info['name']}** ({child['name']})")
                    if link:
                        st.markdown(f"🔗 [Drive'da aç]({link})")
                except FileExistsError as fe:
                    st.error(
                        f"⚠️ {fe} — Drive klasöründe **Content.docx** zaten var, yüklenmedi."
                    )

            with open(local_out, "rb") as f:
                st.download_button(
                    "⬇ Content.docx indir", f,
                    file_name="Content.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )


# =============================================================================
# TAB 3 — AYARLAR
# =============================================================================
def render_settings_tab():
    st.title("Ayarlar")

    cur = config.load()

    if not drive.is_configured():
        st.error("`google_oauth_client.json` yok — Drive entegrasyonu pasif.")

    st.subheader("Default LLM")
    cur_provider = cur.get("llm_provider", "gemini")
    provider_options = {
        "gemini": "Gemini (gemini-2.5-flash)",
        "claude": "Claude (claude-opus-4-7)",
        "openai": "OpenAI (gpt-5.5)",
        "minimax": "MiniMax (MiniMax-M2.7)",
    }
    keys = list(provider_options.keys())
    new_provider = st.selectbox(
        "LLM", keys,
        format_func=lambda k: provider_options[k],
        index=keys.index(cur_provider) if cur_provider in keys else 0,
        key="s_provider",
    )
    if new_provider != cur_provider:
        config.set_value("llm_provider", new_provider)
        st.success(f"Default LLM: **{provider_options[new_provider]}**")

    st.markdown("---")
    st.subheader("API key durumu")
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    has_anth = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_oai = bool(os.getenv("OPENAI_API_KEY"))
    has_minimax = bool(os.getenv("MINIMAX_API_KEY"))
    st.write(f"- **GEMINI_API_KEY**: {'✅ tanımlı' if has_gemini else '❌ eksik (.env\'e ekle)'}")
    st.write(f"- **ANTHROPIC_API_KEY**: {'✅ tanımlı' if has_anth else '❌ eksik (.env\'e ekle)'}")
    st.write(f"- **OPENAI_API_KEY**: {'✅ tanımlı' if has_oai else '❌ eksik (.env\'e ekle)'}")
    st.write(f"- **MINIMAX_API_KEY**: {'✅ tanımlı' if has_minimax else '❌ eksik (.env\'e ekle)'}")

    st.markdown("---")
    st.subheader("Drive cache")
    cache_root = drive_cache.CACHE_ROOT
    if cache_root.exists():
        size = sum(f.stat().st_size for f in cache_root.rglob("*") if f.is_file())
        st.caption(f"`.drive_cache/` boyutu: {size / 1024 / 1024:.1f} MB")
    else:
        st.caption("`.drive_cache/` henüz oluşmadı")
    if st.button("🔄 Cache'i temizle (Drive'dan tekrar indir)", key="s_clear_cache"):
        drive_cache.clear_cache()
        cached_list_folders.clear()
        cached_sync_parent_raw.clear()
        cached_sync_category_assets.clear()
        st.success("Cache temizlendi.")

    st.markdown("---")
    st.subheader("content_prompt.md")
    prompt_initial = load_prompt()
    with st.expander("Prompt'u görüntüle / düzenle", expanded=False):
        edited_prompt = st.text_area(
            "Prompt", prompt_initial, height=400, key="s_prompt_edit",
        )
        if st.button("💾 Promptu kaydet", key="s_prompt_save"):
            PROMPT_FILE.write_text(edited_prompt)
            st.success(f"Kaydedildi: `{PROMPT_FILE.name}`")


with tab_vehicle:
    render_vehicle_tab()

with tab_content:
    render_content_tab()

with tab_settings:
    render_settings_tab()
