"""
pipeline.py — Görsel işleme pipeline'ı
Adımlar: bg removal → inpainting → shadow → composite → text
"""
import os
from io import BytesIO
from pathlib import Path
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

PHOTOROOM_ENDPOINT = "https://image-api.photoroom.com/v2/edit"

_rembg_session = None
_lama = None


def photoroom_edit(input_path: Path, api_key: str = None,
                   padding: float = 0.25) -> Image.Image:
    """PhotoRoom API: bg-remove + AI soft shadow tek çağrıda.
    Döner: gölgeli RGBA Image (transparent zemin, gölge alpha'ya gömülü).
    """
    api_key = api_key or os.environ.get("PHOTOROOM_API_KEY")
    if not api_key:
        raise RuntimeError("PHOTOROOM_API_KEY bulunamadı — .env veya env var olarak ayarla")

    with open(input_path, "rb") as f:
        files = {"imageFile": (input_path.name, f, "image/jpeg")}
        data = {
            "removeBackground": "true",
            "background.color": "00000000",
            "shadow.mode": "ai.soft",
            "textRemoval.mode": "ai.all",
            "padding": str(padding),
        }
        headers = {"x-api-key": api_key}
        r = requests.post(PHOTOROOM_ENDPOINT, data=data, files=files,
                          headers=headers, timeout=60)
    if not r.ok:
        raise RuntimeError(f"PhotoRoom {r.status_code}: {r.text[:500]}")
    return Image.open(BytesIO(r.content)).convert("RGBA")


def get_rembg_session(model: str = "isnet-general-use"):
    """rembg session'ını cache'le, her aracı için yeniden yükleme."""
    global _rembg_session
    if _rembg_session is None:
        from rembg import new_session
        _rembg_session = new_session(model)
    return _rembg_session


def get_lama():
    """LaMa modelini cache'le."""
    global _lama
    if _lama is None:
        from simple_lama_inpainting import SimpleLama
        _lama = SimpleLama()
    return _lama


def remove_background(input_path: Path) -> Image.Image:
    """rembg ile profesyonel bg removal. Çıktı: RGBA PIL Image."""
    from rembg import remove
    with open(input_path, "rb") as f:
        data = f.read()
    out = remove(data, session=get_rembg_session())
    img = Image.open(__import__("io").BytesIO(out)).convert("RGBA")
    # Otomatik crop — tight bounding box
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def inpaint_logos_and_plate(rgb_path: Path, mask_path: Path) -> Image.Image:
    """LaMa ile amblem/plaka silme.
    
    rgb_path: orijinal araç fotoğrafı (henüz bg silinmemiş hali — LaMa için)
    mask_path: silinecek bölgelerin beyaz (255), gerisi siyah (0) olduğu PNG.
    
    Döner: inpaint edilmiş RGB Image (henüz arka planı var, sonra rembg gelecek).
    """
    image = Image.open(rgb_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.NEAREST)
    return get_lama()(image, mask)


def make_shadow(rgba: Image.Image,
                body_width_ratio: float = 1.05,
                body_height_ratio: float = 0.18,
                body_center_y_offset: float = 0.97,
                body_opacity: float = 0.42,
                body_blur_ratio: float = 0.05,
                contact_band: float = 0.15,
                contact_squash: float = 0.30,
                contact_blur: int = 8,
                contact_opacity: float = 0.65) -> Image.Image:
    """Aracın altına gölge:
    Body: silüet-bağımsız uniform yatay oval havuz — gölgenin içinde araba detayı seçilmez.
    Contact: silüet-temelli, tekerlek temas noktalarında koyu nokta gölge.
    """
    w, h = rgba.size
    alpha = rgba.split()[3]
    extra = int(h * 0.25)
    out = Image.new("RGBA", (w, h + extra), (0, 0, 0, 0))

    pad = 100
    body_canvas = Image.new("RGBA", (w + pad * 2, h + extra), (0, 0, 0, 0))
    od = ImageDraw.Draw(body_canvas)
    bw = int(w * body_width_ratio)
    bh = int(h * body_height_ratio)
    bcx = (w + pad * 2) // 2
    bcy = int(h * body_center_y_offset)
    od.ellipse([bcx - bw // 2, bcy - bh // 2, bcx + bw // 2, bcy + bh // 2],
               fill=(0, 0, 0, int(255 * body_opacity)))
    body_blurred = body_canvas.filter(ImageFilter.GaussianBlur(int(h * body_blur_ratio)))
    out.alpha_composite(body_blurred, (-pad, 0))

    c_top = int(h * (1 - contact_band))
    c_alpha = alpha.crop((0, c_top, w, h))
    c_orig_h = c_alpha.height
    c_h = max(int(c_orig_h * contact_squash), 4)
    c_layer = Image.new("RGBA", (w, c_orig_h), (0, 0, 0, 0))
    c_layer.paste(Image.new("RGBA", (w, c_orig_h), (0, 0, 0, int(255 * contact_opacity))), (0, 0), c_alpha)
    c_squashed = c_layer.resize((w, c_h), Image.LANCZOS)
    c_blurred = c_squashed.filter(ImageFilter.GaussianBlur(contact_blur))
    out.alpha_composite(c_blurred, (0, h - c_h // 2))

    return out


def composite_on_template(car_rgba: Image.Image, template_path: Path,
                          width_ratio: float = 0.55,
                          center_x: float = 0.50,
                          center_y: float = 0.55,
                          add_shadow: bool = True,
                          vehicle_alpha_threshold: int = 200) -> Image.Image:
    """Aracı şablona oturt, gölge ekle.

    width_ratio aracın **görünür gövdesine** uygulanır (PhotoRoom gölgesine değil).
    Böylece tüm görsel canvas'ı (vehicle + gölge) bunun dışına taşar — gölge kesilmeden
    yerleşir, vehicle ise sabit boyutta kalır.
    """
    template = Image.open(template_path).convert("RGBA")
    T_W, T_H = template.size

    alpha = car_rgba.split()[3]
    body_mask = alpha.point(lambda p: 255 if p >= vehicle_alpha_threshold else 0)
    body_bbox = body_mask.getbbox() or (0, 0, car_rgba.width, car_rgba.height)
    vehicle_w = body_bbox[2] - body_bbox[0]

    target_v_w = int(T_W * width_ratio)
    scale = target_v_w / vehicle_w

    target_canvas_w = int(round(T_W / scale))
    if target_canvas_w > car_rgba.width:
        pad_total = target_canvas_w - car_rgba.width
        pad_left = pad_total // 2
        padded = Image.new("RGBA", (target_canvas_w, car_rgba.height), (0, 0, 0, 0))
        padded.alpha_composite(car_rgba, (pad_left, 0))
        car_rgba = padded
        body_bbox = (body_bbox[0] + pad_left, body_bbox[1],
                     body_bbox[2] + pad_left, body_bbox[3])

    full_w = int(round(car_rgba.width * scale))
    full_h = int(round(car_rgba.height * scale))
    car_r = car_rgba.resize((full_w, full_h), Image.LANCZOS)

    v_cx = (body_bbox[0] + body_bbox[2]) / 2
    v_cy = (body_bbox[1] + body_bbox[3]) / 2
    cx = int(T_W * center_x)
    cy = int(T_H * center_y)
    x = int(round(cx - v_cx * scale))
    y = int(round(cy - v_cy * scale))

    canvas = template.copy()

    if add_shadow:
        shadow = make_shadow(car_rgba,
                             body_width_ratio=1.25,
                             body_height_ratio=0.10,
                             body_center_y_offset=0.99,
                             body_opacity=0.18,
                             body_blur_ratio=0.06,
                             contact_opacity=0.0)
        sw = int(shadow.width * scale)
        sh = int(shadow.height * scale)
        shadow_r = shadow.resize((sw, sh), Image.LANCZOS)
        canvas.alpha_composite(shadow_r, (x, y))

    canvas.alpha_composite(car_r, (x, y))
    return canvas


BEBAS_FONT = Path(__file__).parent / "templates" / "fonts" / "BebasNeue-Regular.ttf"


def update_text(canvas: Image.Image, title: str, years: str,
                label: str = "COMPATIBLE",
                font_bold: str = None,
                cover_top_ratio: float = 0.795,
                title_color=(0, 74, 173, 255),
                years_color=(75, 157, 220, 255),
                label_color=(15, 49, 128, 255)) -> Image.Image:
    """Alt metin alanını beyazla kapat, yeni metni yaz."""
    canvas = canvas.copy()
    T_W, T_H = canvas.size
    draw = ImageDraw.Draw(canvas)

    text_top = int(T_H * cover_top_ratio)
    draw.rectangle([0, text_top, T_W, T_H], fill=(255, 255, 255, 255))

    if not font_bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",     # macOS
        ]
        font_bold = next((p for p in candidates if Path(p).exists()), candidates[0])

    label_f = ImageFont.truetype(font_bold, int(T_H * 0.022))
    title_f = ImageFont.truetype(str(BEBAS_FONT), 125)
    year_f = ImageFont.truetype(str(BEBAS_FONT), 77.5)

    xt = int(T_W * 0.04)
    draw.text((xt, int(T_H * 0.840)), label, font=label_f, fill=label_color)
    draw.text((xt, int(T_H * 0.880)), title, font=title_f, fill=title_color)
    draw.text((xt, int(T_H * 0.955)), years, font=year_f, fill=years_color)

    return canvas


def process_one(input_image: Path, mask: Path, template: Path,
                title: str, years: str, output: Path,
                width_ratio: float = 0.55) -> None:
    """Bir araçlık tam pipeline."""
    print(f"  [1/4] Inpaint amblem/plaka...")
    if mask and mask.exists():
        cleaned = inpaint_logos_and_plate(input_image, mask)
        # geçici dosyaya yaz, sonra rembg oradan okusun
        tmp = input_image.parent / f".tmp_{input_image.stem}.png"
        cleaned.save(tmp)
        bg_input = tmp
    else:
        print(f"     (mask yok, atlıyorum)")
        bg_input = input_image
        tmp = None
    
    print(f"  [2/4] PhotoRoom: bg sil + AI shadow...")
    car = photoroom_edit(bg_input)

    print(f"  [3/4] Şablona yerleştir...")
    canvas = composite_on_template(car, template, width_ratio=width_ratio,
                                    add_shadow=False)
    
    print(f"  [4/4] Metin güncelle...")
    final = update_text(canvas, title=title, years=years)
    
    output.parent.mkdir(parents=True, exist_ok=True)
    final.convert("RGB").save(output, quality=92)
    
    if tmp and tmp.exists():
        tmp.unlink()
    
    print(f"  ✓ {output}")
