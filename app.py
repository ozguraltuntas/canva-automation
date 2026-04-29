"""app.py — Streamlit GUI.

Çalıştırma: .venv/bin/streamlit run app.py

Akış: foto seç → mask çiz → title/years gir → Drive folder seç → İşle.
"""
import time
from pathlib import Path
import shutil

import streamlit as st
from PIL import Image
from streamlit_drawable_canvas import st_canvas

import pipeline
import drive
import auto_mask

ROOT = Path(__file__).parent
INPUTS = ROOT / "inputs"
MASKS = ROOT / "masks"
TEMPLATES = ROOT / "templates"
OUTPUTS = ROOT / "outputs"
for d in (INPUTS, MASKS, OUTPUTS):
    d.mkdir(exist_ok=True)

DEFAULT_TEMPLATE = TEMPLATES / "mountain.png"
MAX_DISPLAY = 900

st.set_page_config(page_title="Canva Otomasyon", layout="wide")
st.title("Canva Otomasyon — Araç Görsel Üretici")

# ---- Session state init
ss = st.session_state
ss.setdefault("uploaded_path", None)
ss.setdefault("uploaded_name", None)
ss.setdefault("mask_path", None)
ss.setdefault("output_path", None)
ss.setdefault("drive_folder_id", None)
ss.setdefault("drive_folder_name", None)
ss.setdefault("drive_browse_parent", "root")
ss.setdefault("drive_breadcrumb", [("root", "My Drive")])
ss.setdefault("ai_drawing", None)
ss.setdefault("canvas_key_seed", 0)

# =========================================================================
# 1. RESİM SEÇ
# =========================================================================
st.header("1. Araç fotoğrafı")
uploaded = st.file_uploader("Resim seç (jpg/png)", type=["jpg", "jpeg", "png"])
if uploaded is not None:
    target = INPUTS / uploaded.name
    with open(target, "wb") as f:
        f.write(uploaded.getbuffer())
    ss.uploaded_path = target
    ss.uploaded_name = uploaded.name
    # Mask path konvansiyonu (varsa kullan)
    candidate = MASKS / f"{target.stem}.mask.png"
    if candidate.exists():
        ss.mask_path = candidate
    else:
        ss.mask_path = None

if not ss.uploaded_path:
    st.info("Devam etmek için bir araç fotoğrafı yükle.")
    st.stop()

img_path = Path(ss.uploaded_path)
img = Image.open(img_path).convert("RGB")
st.success(f"Yüklendi: **{ss.uploaded_name}** ({img.size[0]}×{img.size[1]})")

# =========================================================================
# 2. MASK ÇİZ
# =========================================================================
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

# Canvas'tan mask üret (sadece kırmızı pixel'ler)
if canvas_result.image_data is not None:
    import numpy as np
    arr = canvas_result.image_data  # RGBA, disp_w × disp_h
    # Alpha > 0 olan yerler boyalı kabul → mask (orijinal boyut)
    alpha = arr[:, :, 3]
    if alpha.max() > 0:
        mask_disp = Image.fromarray(alpha).convert("L")
        mask_full = mask_disp.resize(img.size, Image.NEAREST)
        # Threshold (yumuşak çizgilerin sertleşmesi)
        mask_full = mask_full.point(lambda p: 255 if p > 30 else 0)
        mask_path = MASKS / f"{img_path.stem}.mask.png"
        mask_full.save(mask_path)
        ss.mask_path = mask_path

if ss.mask_path and Path(ss.mask_path).exists():
    nz = sum(1 for p in Image.open(ss.mask_path).getdata() if p > 0)
    st.success(f"Mask hazır: {nz:,} pixel boyalı")
else:
    st.warning("Henüz mask yok. Yukarıdaki resmin üstüne çizmeye başla.")

# =========================================================================
# 3. METİNLER
# =========================================================================
import re

st.header("3. Metinler (alt banner)")
combined = st.text_input(
    "Araç bilgisi (model + yıl aralığı)",
    value="BMW I5 SERIES G60 2024-2028",
    placeholder="örn: Acura ADX 2025-2029",
)

_years_match = re.search(r'\b(\d{4}\s*[-–]\s*\d{2,4})\b', combined)
if _years_match:
    years = _years_match.group(1).replace(' ', '')
    title = combined[:_years_match.start()].strip().rstrip(',').rstrip()
else:
    years = ""
    title = combined.strip()

st.caption(f"📌 Title: **{title or '(boş)'}**  |  Years: **{years or '(yıl bulunamadı)'}**")

# =========================================================================
# 4. GOOGLE DRIVE FOLDER
# =========================================================================
st.header("4. Google Drive — çıktı klasörü")

if not drive.is_configured():
    st.warning(
        "`google_oauth_client.json` proje köküne yerleştirilmemiş. "
        "Drive entegrasyonu pasif — sonuç sadece **lokale** kaydedilecek (`outputs/`)."
    )
else:
    # Folder browser
    try:
        breadcrumb_str = " / ".join(name for _, name in ss.drive_breadcrumb)
        st.caption(f"📁 {breadcrumb_str}")

        col_back, col_select = st.columns([1, 3])
        with col_back:
            if len(ss.drive_breadcrumb) > 1 and st.button("⬆ Üst klasör"):
                ss.drive_breadcrumb = ss.drive_breadcrumb[:-1]
                ss.drive_browse_parent = ss.drive_breadcrumb[-1][0]
                st.rerun()
        with col_select:
            if ss.drive_browse_parent != "root" and st.button(
                f"✓ Buraya yükle: {ss.drive_breadcrumb[-1][1]}"
            ):
                ss.drive_folder_id = ss.drive_browse_parent
                ss.drive_folder_name = ss.drive_breadcrumb[-1][1]
                st.success(f"Hedef: **{ss.drive_folder_name}**")

        with st.spinner("Folder listesi alınıyor..."):
            folders = drive.list_folders(ss.drive_browse_parent)

        if folders:
            cols = st.columns(min(len(folders), 4))
            for i, f in enumerate(folders):
                col = cols[i % len(cols)]
                if col.button(f"📁 {f['name']}", key=f"f_{f['id']}"):
                    ss.drive_breadcrumb.append((f["id"], f["name"]))
                    ss.drive_browse_parent = f["id"]
                    st.rerun()
        else:
            st.caption("(Bu klasörde alt klasör yok)")

        if ss.drive_folder_id:
            st.success(f"📂 Hedef Drive klasörü: **{ss.drive_folder_name}**")

    except Exception as e:
        st.error(f"Drive bağlantısı: {e}")

# =========================================================================
# 5. İŞLE
# =========================================================================
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
                width_ratio=0.55,
            )
            ss.output_path = output_path
            dt = time.time() - t0
            st.success(f"Üretildi: **{output_path.name}** ({dt:.1f} sn)")

            if ss.drive_folder_id and drive.is_configured():
                with st.spinner("Drive'a yükleniyor..."):
                    info = drive.upload_file(output_path, ss.drive_folder_id)
                    link = info.get("webViewLink")
                    st.success(
                        f"Drive'a yüklendi: **{info['name']}** "
                        f"({ss.drive_folder_name})"
                    )
                    if link:
                        st.markdown(f"🔗 [Drive'da aç]({link})")
        except Exception as e:
            st.exception(e)

# =========================================================================
# 6. ÖNİZLEME
# =========================================================================
if ss.output_path and Path(ss.output_path).exists():
    st.header("6. Sonuç")
    st.image(str(ss.output_path), caption=Path(ss.output_path).name)
    with open(ss.output_path, "rb") as f:
        st.download_button("⬇ İndir", f, file_name=Path(ss.output_path).name, mime="image/jpeg")
