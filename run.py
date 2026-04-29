"""
run.py — CSV'deki tüm araçları batch olarak işle.

Kullanım:
    python run.py                    # data.csv'deki HER satırı işler
    python run.py --row 5            # sadece 5. satır
    python run.py --only BMW-i5      # ismine göre filtre
"""
import argparse
import csv
import sys
import time
from pathlib import Path

from pipeline import process_one

ROOT = Path(__file__).parent
INPUTS = ROOT / "inputs"
MASKS = ROOT / "masks"
TEMPLATES = ROOT / "templates"
OUTPUTS = ROOT / "outputs"


def load_rows(csv_path: Path):
    with open(csv_path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="data.csv", help="Veri CSV dosyası")
    ap.add_argument("--row", type=int, help="Sadece N. satırı işle (1-indexli)")
    ap.add_argument("--only", help="Sadece bu image_name'i işle")
    ap.add_argument("--skip-existing", action="store_true",
                    help="outputs/ içinde zaten varsa atla")
    args = ap.parse_args()
    
    csv_path = ROOT / args.csv
    if not csv_path.exists():
        print(f"HATA: {csv_path} bulunamadı")
        sys.exit(1)
    
    rows = load_rows(csv_path)
    if args.row:
        rows = [rows[args.row - 1]]
    if args.only:
        rows = [r for r in rows if r["image"] == args.only]
    
    if not rows:
        print("Hiç satır bulunamadı.")
        sys.exit(0)
    
    print(f"İşlenecek: {len(rows)} satır\n")
    t0 = time.time()
    
    for i, row in enumerate(rows, 1):
        image_name = row["image"]
        title = row["title"]
        years = row["years"]
        template_name = row.get("template", "default")
        width_ratio = float(row.get("width_ratio") or 0.55)
        
        input_image = INPUTS / image_name
        mask = MASKS / f"{Path(image_name).stem}.mask.png"
        template = TEMPLATES / f"{template_name}.png"
        output = OUTPUTS / f"{Path(image_name).stem}_{years}.jpg"
        
        if args.skip_existing and output.exists():
            print(f"[{i}/{len(rows)}] SKIP {image_name} (zaten var)")
            continue
        
        if not input_image.exists():
            print(f"[{i}/{len(rows)}] HATA: {input_image} yok")
            continue
        if not template.exists():
            print(f"[{i}/{len(rows)}] HATA: {template} yok")
            continue
        
        print(f"[{i}/{len(rows)}] {image_name} → {title}")
        try:
            process_one(
                input_image=input_image,
                mask=mask,
                template=template,
                title=title,
                years=years,
                output=output,
                width_ratio=width_ratio,
            )
        except Exception as e:
            print(f"  ✗ HATA: {e}")
    
    dt = time.time() - t0
    print(f"\nBitti. Toplam süre: {dt:.1f}s")


if __name__ == "__main__":
    main()
