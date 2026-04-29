"""auto_mask.py — Replicate / GroundingDINO ile otomatik mask üretimi.

Tekerlek + amblem bbox'larını GroundingDINO ile tespit eder, bbox merkezini
daire (cx, cy, r) olarak döndürür. Streamlit canvas bunları "initial_drawing"
olarak çizer; kullanıcı düzenleyebilir.
"""
import os
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
import replicate
import requests
from PIL import Image, ImageDraw

try:
    import fal_client
    _FAL_AVAILABLE = True
except ImportError:
    _FAL_AVAILABLE = False

GROUNDING_DINO_MODEL = "adirik/grounding-dino"
WHEEL_QUERY = "wheel hub . round car logo on grille . round badge on hood . license plate"

WHEEL_KEYWORDS = ("wheel", "hub", "rim")
EMBLEM_KEYWORDS = ("badge", "emblem", "logo")
PLATE_REJECT = ("plate", "license", "number", "grille", "hood")


def is_available() -> bool:
    return bool(os.environ.get("REPLICATE_API_TOKEN"))


def _bbox_to_circle(box, shrink: float = 1.0,
                    cy_offset_ratio: float = 0.0,
                    min_r: int = 10) -> Tuple[int, int, int]:
    """bbox'tan daire üret. cy_offset_ratio: bbox yüksekliğine göre cy'yi
    aşağı kaydırma oranı (0=ortala, +0.20=aşağı %20, vb.)
    """
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    cx = int((x0 + x1) / 2)
    cy = int((y0 + y1) / 2 + bh * cy_offset_ratio)
    r = int(max(bw, bh) / 2 * shrink)
    return (cx, max(8, cy), max(min_r, r))


def _sam2_refine_wheel(image_url: str, bbox,
                       logo_ratio: float = 0.30) -> Optional[Tuple[int, int, int]]:
    """fal.ai SAM2 ile bbox içinde tekerlek mask'ı al, inscribed circle merkezini bul.
    Döner: (cx, cy, r_logo) — jantın gerçek ortası, logo büyüklüğünde radius.
    Başarısız olursa None.
    """
    if not _FAL_AVAILABLE or not os.environ.get("FAL_KEY"):
        return None
    try:
        x0, y0, x1, y1 = [int(v) for v in bbox]
        result = fal_client.subscribe(
            "fal-ai/sam2/image",
            arguments={
                "image_url": image_url,
                "box_prompts": [
                    {"x_min": x0, "y_min": y0, "x_max": x1, "y_max": y1, "label": 1}
                ],
            },
        )
        mask_url = result.get("image", {}).get("url") if isinstance(result, dict) else None
        if not mask_url:
            return None
        r = requests.get(mask_url, timeout=30)
        r.raise_for_status()
        mask_pil = Image.open(BytesIO(r.content)).convert("L")
        binary = (np.array(mask_pil) > 127).astype(np.uint8)
        if binary.sum() < 100:
            return None
        dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
        _, max_dist, _, max_loc = cv2.minMaxLoc(dist)
        cx, cy = max_loc
        r_logo = max(10, int(max_dist * logo_ratio))
        return (int(cx), int(cy), r_logo)
    except Exception:
        return None


def _refine_wheel_center(image_bgr: np.ndarray,
                         bbox,
                         pad_ratio: float = 0.20,
                         logo_ratio: float = 0.30) -> Optional[Tuple[int, int, int]]:
    """Wheel bbox içinde Hough Circle ile gerçek tekerlek merkezini bul.
    Döner: (cx, cy, r_logo) — merkez orijinal koordinatlarda, r logo büyüklüğünde.
    Daire bulamazsa None.
    """
    h, w = image_bgr.shape[:2]
    x0, y0, x1, y1 = [int(v) for v in bbox]
    bw, bh = x1 - x0, y1 - y0
    pad_x = int(bw * pad_ratio)
    pad_y = int(bh * pad_ratio)
    rx0 = max(0, x0 - pad_x)
    ry0 = max(0, y0 - pad_y)
    rx1 = min(w, x1 + pad_x)
    ry1 = min(h, y1 + pad_y)
    roi = image_bgr[ry0:ry1, rx0:rx1]
    if roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 5)
    expected_r = int(min(bw, bh) / 2)
    min_r = max(8, int(expected_r * 0.55))
    max_r = int(expected_r * 1.20)
    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=max(rx1 - rx0, ry1 - ry0),
        param1=120, param2=20,
        minRadius=min_r, maxRadius=max_r,
    )
    if circles is None or len(circles) == 0:
        return None
    cx_local, cy_local, r_wheel = circles[0][0]
    cx = int(cx_local) + rx0
    cy = int(cy_local) + ry0
    r_logo = max(10, int(r_wheel * logo_ratio))
    return (cx, cy, r_logo)


def _extract_detections(output) -> List[dict]:
    if isinstance(output, dict):
        for key in ("detections", "results", "boxes", "predictions"):
            if key in output and isinstance(output[key], list):
                return output[key]
    if isinstance(output, list):
        return output
    return []


GROUNDING_DINO_VERSION = "adirik/grounding-dino:efd10a8ddc57ea28773327e881ce95e20cc1d734c589f7dd01d2036921ed78aa"


def auto_mask_circles(image_path: Path,
                      box_threshold: float = 0.20,
                      text_threshold: float = 0.20,
                      max_area_ratio: float = 0.10) -> List[Tuple[int, int, int]]:
    """GroundingDINO ile tekerlek + amblem tespiti, daire listesi döndür.
    max_area_ratio: bbox alanı görsel alanının bu oranından büyükse reddet
    (false positive — tüm aracı amblem sanıyor).
    """
    if not is_available():
        raise RuntimeError("REPLICATE_API_TOKEN bulunamadı — .env'e ekle")

    img = Image.open(image_path)
    img_w, img_h = img.size
    img_area = img_w * img_h
    image_bgr = cv2.imread(str(image_path))

    sam_image_url: Optional[str] = None
    if _FAL_AVAILABLE and os.environ.get("FAL_KEY"):
        try:
            sam_image_url = fal_client.upload_file(str(image_path))
        except Exception:
            sam_image_url = None

    client = replicate.Client(api_token=os.environ["REPLICATE_API_TOKEN"])
    with open(image_path, "rb") as f:
        output = client.run(GROUNDING_DINO_VERSION, input={
            "image": f,
            "query": WHEEL_QUERY,
            "box_threshold": box_threshold,
            "text_threshold": text_threshold,
        })

    detections = _extract_detections(output)
    wheels: List[Tuple[Tuple[int, int, int], float]] = []
    emblems: List[Tuple[Tuple[int, int, int], float]] = []
    for det in detections:
        if not isinstance(det, dict):
            continue
        label = (det.get("label") or det.get("class") or "").lower()
        box = det.get("bbox") or det.get("box") or det.get("xyxy")
        if not box or len(box) != 4:
            continue
        if any(k in label for k in PLATE_REJECT):
            continue
        x0, y0, x1, y1 = box
        bw, bh = max(0, x1 - x0), max(0, y1 - y0)
        if bw * bh > img_area * max_area_ratio:
            continue
        conf = float(det.get("confidence") or det.get("score") or 0)
        if any(k in label for k in WHEEL_KEYWORDS):
            sam_circle = _sam2_refine_wheel(sam_image_url, box) if sam_image_url else None
            circle = sam_circle if sam_circle else _bbox_to_circle(box, shrink=0.18)
            wheels.append((circle, conf))
        elif any(k in label for k in EMBLEM_KEYWORDS):
            emblems.append((_bbox_to_circle(box, shrink=1.00, min_r=20), conf))

    def dedupe(items, min_dist=40):
        out = []
        for c, conf in items:
            if all((c[0] - p[0])**2 + (c[1] - p[1])**2 > min_dist**2 for p, _ in out):
                out.append((c, conf))
        return out

    wheels.sort(key=lambda x: -x[1])
    emblems.sort(key=lambda x: -x[1])
    wheels = dedupe(wheels, min_dist=img_w * 0.10)
    emblems = dedupe(emblems, min_dist=img_w * 0.05)
    chosen_wheels = [w[0] for w in wheels[:2]]
    chosen_emblem = [e[0] for e in emblems[:1]]
    return chosen_wheels + chosen_emblem


def circles_to_mask(circles: List[Tuple[int, int, int]],
                    size: Tuple[int, int],
                    dilate: float = 1.1) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for cx, cy, r in circles:
        rr = int(r * dilate)
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
    return mask
