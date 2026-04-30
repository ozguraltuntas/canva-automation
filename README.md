# Canva Otomasyon — Araç Görseli Pipeline

3rd party marketplace araç görselleri otomatik üretir:

**raw araç fotoğrafı → amblem/plaka temizle → arka plan kaldır + AI shadow → şablona oturt → metin yaz → Google Drive'a yükle**

Streamlit GUI ile tek pencere üzerinden çalışır. AI auto-mask + manuel düzenleme hibrit akışı.

---

## Mimari

```
app.py (Streamlit GUI)
   │
   ├─► auto_mask.py
   │     ├─ Replicate (adirik/grounding-dino)         → wheel + emblem bbox
   │     └─ fal.ai (fal-ai/sam2/image)                → wheel mask refinement
   │
   ├─► pipeline.py
   │     ├─ simple-lama-inpainting (lokal)            → mask alanlarını sil
   │     ├─ PhotoRoom API (image-api.photoroom.com)   → bg removal + AI shadow + plate text removal
   │     ├─ composite_on_template (PIL)               → mountain.png üstüne yerleştir
   │     └─ update_text (PIL ImageDraw)               → alt banner: COMPATIBLE / TITLE / YEARS
   │
   └─► drive.py (Google Drive API)                    → Drive folder picker + upload
```

**Eski CLI yöntemi** (`mask_tool.py` + `run.py`) hâlâ çalışır ama Streamlit ana akış olarak kullanılıyor.

---

## Kullanılan ücretli servisler

| Servis | Ne için | Maliyet/araç (yaklaşık) |
|---|---|---|
| **PhotoRoom API** | Background removal + AI Shadow Soft + plaka silme (`textRemoval.mode=ai.all`) | ~$0.10 (production), sandbox ücretsiz (watermark'lı) |
| **Replicate** (`adirik/grounding-dino`) | Tekerlek + amblem **bbox tespiti** (text-prompted detection) | ~$0.005 |
| **fal.ai** (`fal-ai/sam2/image`) | Tekerlek **gerçek mask** + inscribed circle merkezi | ~$0.005 (2 wheel × çağrı) |
| **Toplam** | | **~$0.11/araç** (production) |

Lokal/ücretsiz: LaMa inpainting (simple-lama-inpainting), Streamlit, PIL.

---

## Kurulum (tek seferlik)

### 1. Python 3.13 + Tk

```bash
brew install python-tk@3.13
```

(macOS Homebrew Python 3.13 kullanıyor; mask_tool.py için Tk gerekiyor.)

### 2. Venv + bağımlılıklar

```bash
cd canva_otomasyon
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --no-deps simple-lama-inpainting   # numpy<2 sorunu için
.venv/bin/pip install "rembg[cpu]"
```

İlk kullanımda LaMa modeli (~196 MB) ve rembg ISNet modeli (~179 MB) inecektir.

### 3. API key'ler — `.env`

Proje köküne `.env` oluştur:

```
PHOTOROOM_API_KEY=sandbox_sk_pr_default_...   # https://www.photoroom.com/api
REPLICATE_API_TOKEN=r8_...                     # https://replicate.com/account/api-tokens
FAL_KEY=<key_id>:<key_secret>                  # https://fal.ai/dashboard/keys
```

Production'a geçiş: PhotoRoom sandbox key'i live key ile değiştir (watermark gider).

### 4. Google Drive OAuth — `google_oauth_client.json`

Çıktıyı Drive'a otomatik yüklemek için:

1. https://console.cloud.google.com → proje seç
2. APIs & Services → Library → "Google Drive API" → Enable
3. APIs & Services → OAuth consent screen → External
   - Test users sekmesinde **Drive'a yazılacak hesabı** ekle
4. APIs & Services → Credentials → "+ CREATE CREDENTIALS" → OAuth client ID
   - Application type: **Desktop app**
   - DOWNLOAD JSON
5. JSON'ı `google_oauth_client.json` adıyla proje köküne koy

İlk çalıştırmada tarayıcıda OAuth onay ekranı açılır → hedef Drive hesabını seç → "Allow". Token `.drive_token.pickle`'a saklanır, sonraki çağrılarda otomatik kullanılır.

`google_oauth_client.json` yoksa Drive bölümü pasif kalır, çıktı sadece lokal `outputs/`'a yazılır.

### 5. Şablon

`templates/mountain.png` proje ile birlikte gelir (dağ panoraması template). Yeni şablonlar `templates/<isim>.png` olarak eklenebilir; şu an Streamlit GUI hardcoded olarak `mountain.png` kullanıyor.

---

## Çalıştırma

```bash
.venv/bin/streamlit run app.py
```

Tarayıcıda otomatik `http://localhost:8501` açılır.

### GUI akışı

1. **📂 Bilgisayardan yükle** → araç fotoğrafı seç (jpg/png)
2. **Mask çiz** (silinecek bölgeler):
   - **🎯 AI ile otomatik mask** — Replicate GroundingDINO + fal.ai SAM2 ile **2 jant logosu + 1 ön/arka amblem** otomatik tespit (~6 sn). Plaka mask'a girmez (PhotoRoom otomatik silecek).
   - **🔴 Daire çiz** — tek tıkla-sürükle ile daire ekle
   - **✏️ Boya** — serbest çizim
   - **↔️ Taşı/Boyutlandır** — mevcut daireleri ayarla
3. **Araç bilgisi** → "BMW I5 SERIES G60 2024-2028" gibi yapıştır → otomatik parse (title + years)
4. **Google Drive klasörü** seç (opsiyonel)
5. **🚀 İşle ve üret** — ~17 sn:
   - LaMa inpaint (mask alanları silinir)
   - PhotoRoom (bg + shadow + plate text)
   - Mountain template + alt metin
   - `outputs/<image>_<years>.jpg` kaydedilir
   - Drive klasörü seçildiyse oraya yüklenir

### Eski CLI yöntemi (yedek)

```bash
.venv/bin/python mask_tool.py inputs/<image>.jpg   # Tk pencerede mask çiz
# data.csv satırı eklendikten sonra:
.venv/bin/python run.py --only <image>.jpg
```

---

## Dosya yapısı

```
canva_otomasyon/
├── app.py                    # Streamlit GUI (ana akış)
├── pipeline.py               # process_one + photoroom_edit + composite + text
├── auto_mask.py              # Replicate GroundingDINO + fal.ai SAM2
├── drive.py                  # Google Drive auth + folder list + upload
├── mask_tool.py              # Tk-based mask editor (eski CLI)
├── run.py                    # CSV batch runner (eski CLI)
├── templates/mountain.png    # Şablon
├── inputs/                   # (runtime — uploaded fotos)
├── masks/                    # (runtime — drawn/AI masks)
├── outputs/                  # (runtime — final JPGs, gitignore)
├── data.csv                  # CSV CLI yöntemi için
├── requirements.txt
├── .env                      # API keys (gitignore)
├── google_oauth_client.json  # Drive OAuth (gitignore)
└── .drive_token.pickle       # Drive token (gitignore, auto-generated)
```

`.gitignore` korur: `.env`, `.venv/`, `*.pt`, `outputs/`, OAuth dosyaları.

---

## Bilinen sınırlamalar

- **AI auto-mask kabaca doğru** — daireler %80 doğru yere konur, son rötuşu kullanıcı "Taşı/Boyutlandır" ile ~5 sn'de yapar. 3D perspektif kayması için manuel düzeltme şart.
- **netcarshow.com URL'den çekilemiyor** — site agresif anti-bot uyguluyor (Playwright/CDP/stealth bile aşamadı, IP ban yiyoruz). Bu site için **Save Image As + Upload** manuel yol kullanılmalı. Diğer sitelerden URL ile çekme şu an UI'da yok ama `requests.get` ile basitçe eklenebilir.
- **Tek template (`mountain.png`)** hardcoded. Şablon seçici GUI ileride.
- **Sandbox PhotoRoom watermark** — production key alındığında kaybolur.
- **macOS only**: Homebrew Python + Tk varsayımı; Linux/Windows için path'ler değişir.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `ModuleNotFoundError: _tkinter` | `brew install python-tk@3.13` çalıştırılmamış |
| `pip install` `numpy<2` çakışması | `simple-lama-inpainting`'i `--no-deps` ile yükle |
| `rembg`: "No onnxruntime backend" | `pip install "rembg[cpu]"` |
| Drive bölümü "yapılandırılmamış" | `google_oauth_client.json` proje köküne koy + restart |
| OAuth "App not verified" | Cloud Console → OAuth consent screen → Test users → hesabı ekle, "Continue (unsafe)" |
| `cannot open resource` (font) | `pipeline.py` macOS Arial fallback'i ile ayarlı; Linux'ta DejaVu yolu |

---

## Geliştirme notları

- **Sırlar git'e gitmesin:** `.env`, `google_oauth_client.json`, `.drive_token.pickle` `.gitignore`'da
- **Repo:** https://github.com/ozguraltuntas/canva-automation
- **Test verisi:** `inputs/`, `masks/`, `outputs/` klasörleri runtime — repo'da boş tutulur (`.gitkeep`)
- **Production geçişi:** PhotoRoom sandbox → live key (`.env` güncelle), gerisi çalışır
