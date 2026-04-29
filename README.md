# Canva Otomasyon — Araç Görseli Pipeline

3rd party marketplace görsellerini otomatik üretir:
**raw araç fotoğrafı → arka plan kaldır → amblem/plaka sil (LaMa) → şablona oturt → metin yaz → hazır PNG**

## Kurulum (tek seferlik, ~10 dk)

### 1. Python 3.10+ kurulu olduğundan emin ol

```bash
python --version    # 3.10+ olmalı
```

Yoksa: https://www.python.org/downloads/

### 2. Bu klasöre gel ve paketleri kur

```bash
cd canva_otomasyon
pip install -r requirements.txt
```

İlk çalıştırmada `rembg` ve `simple-lama-inpainting` modelleri internetten iner (~250 MB toplam, sadece bir kez).

### 3. Şablonunu yerleştir

`templates/mountain.png` olarak senin Canva-2 şablonunu (dağ panoraması, metin alanı boş) koy.
İstersen başka şablonlar da ekle: `templates/forest.png`, `templates/desert.png` vb.

CSV'de hangi şablonu kullanacağın `template` kolonunda belirtilir.

## İlk araç için (her yeni model = 1 kez yapılacak)

1. Araç fotoğrafını `inputs/` klasörüne koy. Örn: `inputs/BMW-i5.jpg`

2. Maskeyi çiz (silinecek bölgeleri işaretle: ön amblem + jant amblemleri + plaka):
   ```bash
   python mask_tool.py inputs/BMW-i5.jpg
   ```
   - **Sol tık + sürükle**: silinecek yeri kırmızıyla boya
   - **Sağ tık**: yanlış boyadığını sil
   - **`[`** / **`]`**: fırça boyu
   - **S**: kaydet ve çık (otomatik olarak `masks/BMW-i5.mask.png` olur)
   - **Q**: kaydetmeden çık

3. `data.csv`'ye satır ekle:
   ```csv
   image,title,years,template,width_ratio
   BMW-i5.jpg,BMW I5 SERIES G60,2024-2028,mountain,0.55
   ```

## Çalıştırma

**Tüm CSV'yi işle:**
```bash
python run.py
```

**Tek satır:**
```bash
python run.py --row 1
python run.py --only BMW-i5.jpg
```

**Daha önce üretilenleri atla (yeni eklenenleri işle):**
```bash
python run.py --skip-existing
```

Çıktılar: `outputs/BMW-i5_2024-2028.jpg`

## CSV Kolonları

| Kolon | Zorunlu | Açıklama |
|---|---|---|
| `image` | ✓ | `inputs/` içindeki dosya adı |
| `title` | ✓ | Alt başlık (örn: "BMW I5 SERIES G60") |
| `years` | ✓ | Yıl aralığı (örn: "2024-2028") |
| `template` | – | `templates/` içindeki PNG adı (uzantısız), default: `default` |
| `width_ratio` | – | Aracın görsel içindeki genişlik oranı (0.40 - 0.65), default: `0.55` |

## İnce ayar

**Aracın pozisyonu / boyutu yanlışsa:** CSV'de `width_ratio`'yu değiştir, ya da `pipeline.py` içindeki `composite_on_template` çağrısının `center_x`, `center_y` değerlerini değiştir.

**Metin pozisyonu / fontu / rengi:** `pipeline.py` içindeki `update_text` fonksiyonunda. İstersen bunları da config dosyasına çıkarabilirim.

**Gölge daha koyu / daha açık:** `make_shadow(opacity=...)` (default 0.45).

## Performans

- İlk araç: ~30 sn (modeller cache'leniyor)
- Sonraki araçlar: ~3-5 sn / araç (CPU üzerinde)
- GPU varsa: ~1-2 sn / araç (rembg ve LaMa otomatik CUDA kullanır)

200 araç ≈ 15 dk (CPU), ≈ 5 dk (GPU).

## Sorun giderme

**"isnet-general-use modeli inmedi"**: İlk çalıştırmada GitHub'dan iner. Network engelliyorsa VPN dene.

**LaMa kalitesi düşük**: Maskeni biraz daha **GENİŞ** yap — silinecek bölgenin 5-10px etrafını da kapsa. LaMa, kenardaki dokuyu örnek alarak doldurur, dar maskede artefakt çıkar.

**Aracın altı sert kesilmiş görünüyor**: rembg'in kesimi temizdir, ama "rembg-greenscreen" yerine `isnet-general-use` modelini kullandığından emin ol (`pipeline.py` → `get_rembg_session` fonksiyonu).
