"""
mask_tool.py — Yeni bir araç eklerken maskeyi interaktif olarak çiz.

Kullanım:
    python mask_tool.py inputs/BMW-i5.jpg
    
Sol tıkla + sürükle: silinecek bölgeyi boya (amblem, plaka, vb.)
Sağ tıkla + sürükle: silme (yanlış boyadığın yeri geri al)
[ ve ] tuşları: fırça boyutunu küçült/büyüt
S tuşu: kaydet ve çık (masks/<isim>.mask.png olarak)
Q tuşu: kaydetmeden çık
"""
import sys
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk


class MaskPainter:
    def __init__(self, image_path: Path):
        self.image_path = image_path
        self.original = Image.open(image_path).convert("RGB")
        
        # Ekrana sığması için scale (max 1400px)
        max_dim = 1400
        scale = min(max_dim / self.original.width,
                    max_dim / self.original.height, 1.0)
        self.scale = scale
        self.disp_size = (int(self.original.width * scale),
                          int(self.original.height * scale))
        self.disp_image = self.original.resize(self.disp_size, Image.LANCZOS)
        
        # Maske her zaman orijinal boyutta
        self.mask = Image.new("L", self.original.size, 0)
        self.mask_draw = ImageDraw.Draw(self.mask)
        
        # UI
        self.root = tk.Tk()
        self.root.title(f"Maske: {image_path.name}  —  S:kaydet  Q:çık  []:fırça")
        
        self.brush = 35
        self.last = None
        
        self.canvas = tk.Canvas(self.root, width=self.disp_size[0],
                                height=self.disp_size[1], cursor="crosshair")
        self.canvas.pack()
        self.tk_img = ImageTk.PhotoImage(self.disp_image)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        
        self.overlay_id = None
        self.refresh_overlay()
        
        # Status bar
        self.status = tk.Label(self.root, text="", anchor="w")
        self.status.pack(fill="x")
        self.update_status()
        
        # Events
        # Ctrl basılı + sol-tık → silme (trackpad'de sağ-tık+sürükle zor)
        def _left(e):
            self.paint(e, value=0 if (e.state & 0x4) else 255)
        self.canvas.bind("<B1-Motion>", _left)
        self.canvas.bind("<Button-1>", _left)
        self.canvas.bind("<B3-Motion>", lambda e: self.paint(e, value=0))
        self.canvas.bind("<Button-3>", lambda e: self.paint(e, value=0))
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "last", None))
        self.canvas.bind("<ButtonRelease-3>", lambda e: setattr(self, "last", None))
        self.root.bind("<Key>", self.key)
        self.root.focus_set()
    
    def paint(self, event, value):
        # Ekran koordinatından orijinal koordinatına dönüştür
        ox = int(event.x / self.scale)
        oy = int(event.y / self.scale)
        r = int(self.brush / self.scale / 2)
        
        if self.last is not None:
            self.mask_draw.line([self.last, (ox, oy)], fill=value, width=r * 2)
        self.mask_draw.ellipse([ox - r, oy - r, ox + r, oy + r], fill=value)
        self.last = (ox, oy)
        self.refresh_overlay()
    
    def refresh_overlay(self):
        # Maskeyi yarı saydam kırmızı olarak göster
        disp_mask = self.mask.resize(self.disp_size, Image.NEAREST)
        red = Image.new("RGBA", self.disp_size, (255, 0, 0, 0))
        red.putalpha(disp_mask.point(lambda p: int(p * 0.5)))
        composed = self.disp_image.convert("RGBA")
        composed.alpha_composite(red)
        self.tk_img = ImageTk.PhotoImage(composed)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
    
    def update_status(self):
        self.status.config(text=f"Fırça: {self.brush}px  |  Sol-tık: boya  |  Ctrl+Sol veya Sağ-tık: sil  |  [/]: fırça boyu  |  S: kaydet  |  Q: çık")
    
    def key(self, event):
        k = event.keysym.lower()
        if k == "s":
            self.save()
            self.root.destroy()
        elif k == "q":
            self.root.destroy()
        elif k == "bracketleft":
            self.brush = max(5, self.brush - 5)
            self.update_status()
        elif k == "bracketright":
            self.brush = min(200, self.brush + 5)
            self.update_status()
    
    def save(self):
        out_dir = self.image_path.parent.parent / "masks"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{self.image_path.stem}.mask.png"
        self.mask.save(out_path)
        print(f"✓ Kaydedildi: {out_path}")
    
    def run(self):
        self.root.mainloop()


def main():
    if len(sys.argv) < 2:
        print("Kullanım: python mask_tool.py inputs/<image>.jpg")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"HATA: {path} yok")
        sys.exit(1)
    MaskPainter(path).run()


if __name__ == "__main__":
    main()
