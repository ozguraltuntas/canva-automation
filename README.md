# Canva Otomasyon — Araç Görseli + Content.docx Pipeline

Amazon / eBay / 3rd party marketplace ürünleri için **iki çıktı** üretir:

1. **Araç görseli** — `raw araç fotoğrafı → amblem/plaka temizle → arka plan kaldır + AI shadow → mountain template'e oturt → Bebas Neue text → Drive`
2. **Content.docx** — `standart_images + raw foto + Text edit.docx + user notes → Claude/OpenAI vision → TITLE / 5 BULLETS / DESCRIPTION / GENERIC KEYWORDS → docx → Drive`

Streamlit GUI tek pencere üzerinden çalışır, 3 tab: **🚗 Araç Görseli / 📝 Content.docx / ⚙️ Ayarlar**.

---

## Mimari

### 3 tab

```
🚗 Araç Görseli                          📝 Content.docx                    ⚙️ Ayarlar
─────────────────                        ────────────────                   ──────────
Brand picker (üstte)                     Brand picker (üstte)               Default LLM seçimi
1. Foto yükle                            Category dropdown                  API key durumu
2. Mask çiz (manuel veya AI auto)        ↳ standart_images thumbnails       Drive cache temizle
3. Title + years gir                     ↳ Text edit.docx preview           content_prompt.md edit
4. Drive hedef (Cat→Parent→Child)        Parent (model) dropdown
5. İşle ve üret → 5.jpg                  ↳ raw thumbnails
   → Drive'a yüklenir                    Child (part_number) dropdown
                                         Notlar + OEM input + checkboxlar
                                         🚀 Üret → 4 bölüm (edit edilebilir)
                                         💾 Drive'a Content.docx upload
```

Brand seçimi **iki tab arasında paylaşılır** (config üzerinden). Aynı şekilde
seçilen Category/Parent/Child da senkronize olur — Vehicle tab'da seçim yaptığında
Content tab'da da geçerli olur (ve tersi).

### Kod path'i

```
app.py (Streamlit GUI)
├─ render_vehicle_tab()
│   ├─ _render_brand_picker("v")             ← Drive folder browser, brand seçer
│   ├─ st_canvas mask çiz / auto_mask        ← Replicate GroundingDINO + fal.ai SAM2
│   ├─ _render_drive_hierarchy_picker("v")   ← Cat/Parent/Child dropdownları (step 4)
│   └─ pipeline.process_one()
│       ├─ simple-lama-inpainting (lokal)    ← mask alanlarını sil
│       ├─ PhotoRoom Plus API                ← bg removal + AI shadow + plate text removal
│       ├─ composite_on_template (PIL)       ← mountain.png üstüne yerleştir (width_ratio=0.6875)
│       └─ update_text (PIL ImageDraw)       ← title (Bebas 125 #004aad) + years (Bebas 77.5 #4b9ddc)
│
├─ render_content_tab()
│   ├─ _render_brand_picker("c")             ← aynı brand picker
│   ├─ Category dropdown                     ← drive_cache.sync_category_assets()
│   │     standart_images thumbnails + Text edit.docx preview
│   ├─ Parent (model) dropdown               ← drive_cache.sync_parent_raw()
│   │     raw thumbnails
│   ├─ Child (part_number) dropdown
│   └─ @st.fragment _render_content_io_fragment()
│       ├─ Notlar + OEM input + 2 OEM checkbox
│       ├─ 🚀 Üret → content_pipeline.generate_content()
│       │   ├─ collect_images()              ← .drive_cache path'lerinden image listesi
│       │   ├─ call_claude / call_openai     ← base64 vision API
│       │   ├─ parse_llm_output()            ← TITLE/BULLETS/DESC/KEYWORDS regex split
│       │   ├─ apply_oem()                   ← title/keywords sonuna OEM ekle
│       │   └─ validate_lengths()            ← 200/250 char check (uyarı)
│       └─ 💾 → content_pipeline.save_content_docx() + drive.upload_file_strict()
│
└─ render_settings_tab()
    Default LLM (Claude/OpenAI), API key durumu, .drive_cache temizle, prompt edit
```

### Drive klasör hiyerarşisi

```
Silbak/                              ← brand_folder (her tab üstünde picker)
└── wiper blade/                     ← category (dropdown, "standart_images" hariç)
    ├── standart_images/             ← LLM'e gidecek brand görselleri
    ├── Text edit.docx               ← LLM'e gidecek metadata (otoriter — aşağıya bkz)
    └── SB2622B/                     ← parent / model (dropdown, "raw" hariç)
        ├── raw/                     ← telefon fotoları (LLM'e gider)
        ├── SB2622BA/                ← child = part_number (dropdown, hedef klasör)
        │   ├── Content.docx         ← üretilen
        │   └── 5.jpg                ← üretilen
        └── SB2622BB/
```

**Nereye ne yüklenir:**
- `5.jpg` → seçili child klasörü (`last_child_id`)
- `Content.docx` → seçili child klasörü
- Drive'da aynı isimde dosya varsa **kırmızı uyarı**, yüklenmez (LLM çağrısı bile yapılmaz, kota harcanmasın diye)

---

## Dosya yapısı

```
canva-automation/
├── app.py                          # Streamlit GUI (3 tab) — 840+ satır
├── pipeline.py                     # Araç görseli üretimi (LaMa + PhotoRoom + composite + text)
├── content_pipeline.py             # ★ YENİ — LLM (Claude/OpenAI vision) + parse + OEM + docx
├── drive.py                        # ★ EXTENDED — list_files, find_child_by_name, download_file,
│                                   #              file_exists, upload_file_strict
├── drive_cache.py                  # ★ YENİ — Drive folder → .drive_cache/ sync (mtime-based)
├── config.py                       # ★ YENİ — app_config.json read/write helpers (persisted UI state)
├── content_prompt.md               # ★ YENİ — Amazon listing prompt'u (Settings'ten edit edilebilir)
├── auto_mask.py                    # Replicate GroundingDINO + fal.ai SAM2 (araç görseli için)
├── mask_tool.py                    # Tk-based mask editor (eski CLI yöntemi — yedek)
├── run.py                          # CSV batch runner (eski CLI — yedek)
├── templates/
│   ├── mountain.png                # araç görseli şablonu (hardcoded)
│   └── fonts/BebasNeue-Regular.ttf # title + years fontu
├── inputs/                         # runtime — yüklenen fotoğraflar
├── masks/                          # runtime — çizilen mask'lar
├── outputs/                        # runtime — üretilen 5.jpg + Content.docx (gitignore)
├── .drive_cache/                   # ★ YENİ — Drive'dan indirilen görseller (gitignore)
├── data.csv                        # eski CSV CLI yöntemi için
├── app_config.json                 # ★ YENİ — runtime UI state (gitignore)
│                                   #   brand_folder_id, llm_provider, last_category/parent/child_id
├── requirements.txt                # + anthropic, openai, python-docx
├── .env                            # API keys (gitignore)
├── google_oauth_client.json        # Drive OAuth (gitignore)
└── .drive_token.pickle             # Drive token (gitignore, auto-generated)
```

`.gitignore` korur: `.env`, `.venv/`, `*.pt`, `outputs/`, `app_config.json`, `.drive_cache/`, OAuth dosyaları.

---

## Kullanılan ücretli servisler

### Araç görseli pipeline (mevcut)

| Servis | Ne için | Maliyet/araç |
|---|---|---|
| **PhotoRoom Plus** | bg removal + AI Shadow Soft + `textRemoval.mode=ai.all` (plaka silme) | $0.10 ($100/ay 1000 image kotası) |
| **Replicate** (`adirik/grounding-dino`) | tekerlek + amblem bbox tespiti | ~$0.005 |
| **fal.ai** (`fal-ai/sam2/image`) | tekerlek mask refinement | ~$0.005 |

PhotoRoom Plus zorunlu — Basic plan'da AI Shadows ve GenAI text removal yok.
Kota kontrolü: `curl -H "x-api-key: $PHOTOROOM_API_KEY" https://image-api.photoroom.com/v2/account`

### Content.docx pipeline (yeni)

| Servis | Ne için | Model |
|---|---|---|
| **Anthropic Claude** | TITLE / BULLETS / DESCRIPTION / KEYWORDS üretimi (vision) | `claude-opus-4-7` (1M context) |
| **OpenAI** | aynı, alternatif | `gpt-5.5` (1M context) — ⚠️ uçtan uca doğrulanmadı |

Default LLM Settings tab'ından seçilir (`app_config.json`'a kaydedilir).
Combobox'tan tek seferlik değişim yok — global default.

---

## Kurulum

### 1. Python 3.13 + Tk

```bash
brew install python-tk@3.13
```

### 2. Venv + bağımlılıklar

```bash
cd canva-automation
/opt/homebrew/bin/python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --no-deps simple-lama-inpainting   # numpy<2 sorunu için
.venv/bin/pip install "rembg[cpu]"
```

İlk kullanımda LaMa modeli (~196 MB) ve rembg ISNet (~179 MB) inecektir.

### 3. `.env` dosyası

```
PHOTOROOM_API_KEY=sk_pr_default_...     # PhotoRoom Plus live key
REPLICATE_API_TOKEN=r8_...
FAL_KEY=<key_id>:<key_secret>
ANTHROPIC_API_KEY=sk-ant-...            # Content.docx için
OPENAI_API_KEY=sk-...                   # Content.docx için (opsiyonel)
```

İkisinden en az biri gerekli (default olarak hangisi seçildiyse). Diğeri eksikse
o LLM seçilemez.

### 4. Google Drive OAuth

`google_oauth_client.json` proje köküne — Cloud Console → Desktop OAuth client.
SCOPES: `drive.file` + `drive.readonly`.

İlk çalıştırmada tarayıcıda OAuth ekranı, token `.drive_token.pickle`'a saklanır.

### 5. Şablon ve font

`templates/mountain.png` ve `templates/fonts/BebasNeue-Regular.ttf` repo ile gelir.

---

## Çalıştırma

```bash
.venv/bin/streamlit run app.py
```

`http://localhost:8501` otomatik açılır.

---

## Content.docx üretimi — uçtan uca akış

1. **⚙️ Ayarlar → Default LLM** — Claude veya OpenAI seç.
2. **🚗 Araç Görseli veya 📝 Content.docx tab** — sayfanın en üstündeki **brand picker**'dan
   brand klasörünü seç (örn. `Silbak`). Brand iki tab arasında paylaşılır.
3. **Category dropdown** — `wiper blade` vb. seç. Otomatik olarak:
   - `standart_images/` içeriği `.drive_cache/categories/{cat_id}/standart_images/`'a indirilir
   - `Text edit.docx` indirilir, preview'i görünür
4. **Parent (model) dropdown** — `SB2622B` vb. seç. `raw/` içeriği indirilir, thumbnails görünür.
5. **Child (part_number) dropdown** — `SB2622BA` vb. seç. Bu **hedef klasör** (Content.docx + 5.jpg buraya).
6. **Notlar** — ürüne özel bilgi (örn. `Mercedes-Benz GL-Class 2006-2012`)
7. **OEM kod(lar)** — literal append için (örn. `A2518200845 A1234567890`)
   - "Title sonuna ekle" / "Generic Keywords sonuna ekle" checkbox'larıyla seç
8. **🚀 Content.docx üret** — Drive ön-kontrol (varsa LLM çağrılmaz), sonra Claude/OpenAI çağrılır,
   ~10-20 sn içinde 4 bölüm üretilir.
9. **Sonuç** — TITLE / BULLET POINTS / DESCRIPTION / GENERIC KEYWORDS text_area'larında edit edebilirsin.
   200/250 char limitleri aşılırsa kırmızı uyarı (engellemiyor).
10. **💾 Drive'a yükle** — `outputs/Content_<child_id>.docx` lokal kaydedilir, ardından Drive'da seçili
    child klasörüne `Content.docx` olarak yüklenir. Aynı isimde varsa kırmızı uyarı.

---

## UI / state pattern'leri (önemli — geliştirirken hatırla)

### Editable combobox (`_select_dropdown_with_id`)

Streamlit `selectbox`'ı kapalıyken non-editable buton, `accept_new_options=True` bile
sadece dropdown açıkken filter input'u veriyor. Native copy/paste/backspace/sağ tık
istediğimiz için **gerçek `st.text_input`** kullanıyoruz, listeden seçim için altta
collapsible expander içinde ayrı bir `st.selectbox`:

```
Category
[wiper blade________________________________________]
▶ 📋 Listeden seç (3 öğe)
```

State:
- `ss[f"{key}_text"]` — text_input değeri (source of truth)
- `ss[f"{key}_sel"]` — expander içindeki selectbox değeri
- `ss[f"{key}__items_sig"]` — items listesinin id tuple'ı (parent değişince child reset için)

Sync:
- text_input değişip geçerli bir isim ise → `ss[sel_key] = cur_text` ile selectbox senkronize edilir
- selectbox değişirse `on_change` callback `ss[text_key] = ss[sel_key]` ile text input senkronize
- items listesi değişirse (parent → child cascade) hem text_key hem sel_key reset edilir, ilk öğe seçilir

### Brand picker (`_render_brand_picker`)

Hem Vehicle hem Content tab'ın üstünde. Brand setliyse compact view:
```
🏷️ Brand: **Silbak**    [🔄 değiştir]
```
Boşsa ya da "değiştir" basıldıysa inline expander içinde `render_drive_folder_browser`.

State: `ss[f"{prefix}_show_brand_picker"]` — picker açık/kapalı toggle.

### Fragment (`@st.fragment _render_content_io_fragment`)

Notlar/OEM/Üret/Sonuç bölümü `@st.fragment` içinde. Streamlit her widget etkileşiminde
tüm scripti rerun eder; fragment ile sadece bu bölüm rerun olur → üstteki standart_images
ve raw thumbnails text/checkbox değişiminde flicker etmez.

### Drive cache (`drive_cache.py`)

`.drive_cache/` altında klasör hiyerarşisi:
- `categories/{cat_id}/standart_images/<file>.jpg`
- `categories/{cat_id}/Text edit.docx`
- `parents/{parent_id}/raw/<file>.jpg`

`drive.download_file` — `modifiedTime` parametresi ile cache valid ise indirme atlar.
Google Docs/Sheets/Slides → Office formatına export.

`Settings → 🔄 Cache temizle` ile force re-download.

### Config persistence (`config.py`)

`app_config.json` runtime UI state'i:
```json
{
  "brand_folder_id": "...", "brand_folder_name": "Silbak",
  "llm_provider": "claude",
  "last_category_id": "...", "last_category_name": "wiper blade",
  "last_parent_id": "...", "last_parent_name": "SB2622B",
  "last_child_id": "...", "last_child_name": "SB2622BA"
}
```

Bu dosya gitignore'da. Tab'lar arası senkron config üzerinden çalışır.

### Text edit.docx — LLM'e otoriter veri

`content_pipeline._build_user_text_block` ve `RESPONSE_OVERRIDE` blokları LLM'e
şunu söyler: "Sistem prompt'u 'sadece görseldeki text'i kullan' diyor ama
**'## Category metadata' ve '## Product-specific notes' bölümlerindeki bilgi
verified facts** — onları da kullan." Yoksa `content_prompt.md`'deki "Use ONLY
text that is visible in the image" kuralı yüzünden Text edit.docx içeriği LLM
tarafından yok sayılırdı.

### OEM behavior

LLM'e gönderilirken "**Do NOT include them yourself**" deniliyor. `apply_oem`
parse'tan SONRA literal append yapıyor (title ve/veya keywords sonuna boşluk + OEM).
Title 200 char aşarsa uyarı (engellemiyor).

---

## Bilinen sınırlamalar

- **GPT-5.5 doğrulanmadı** — model adı kodda var ama gerçek API çağrısı test edilmedi.
  Default Claude kullan.
- **Tek template (`mountain.png`)** araç görseli için hardcoded.
  Araç şablon genişliğinin **%68.75**'ini kaplar (`width_ratio=0.6875`,
  `app.py` içinde `pipeline.process_one` çağrısında set edilir).
- **netcarshow.com URL'den çekilemiyor** (anti-bot) — Save Image As + manual upload kullan.
- **macOS only** — Homebrew Python + Tk path'leri.
- **AI auto-mask kabaca doğru** — son rötuş manuel "Taşı/Boyutlandır" ile.
- **Cross-tab combobox state** — bir tab'ta seçim değişince diğer tab'a geçince
  config üzerinden senkron olur, ama widget state stale kalabilir (Cmd+R ile çözülür).
- **Drive folder duplicate detection** — sadece isme göre. Drive'da aynı isimde 2 dosya varsa
  ilki güncellenir.

---

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `ModuleNotFoundError: _tkinter` | `brew install python-tk@3.13` |
| `pip install` `numpy<2` çakışması | `simple-lama-inpainting`'i `--no-deps` ile yükle |
| `rembg`: "No onnxruntime backend" | `pip install "rembg[cpu]"` |
| Drive bölümü "yapılandırılmamış" | `google_oauth_client.json` proje köküne koy + restart |
| OAuth "App not verified" | Cloud Console → OAuth consent screen → Test users → hesabı ekle |
| `cannot open resource` (font) | `pipeline.py` macOS Arial fallback ile ayarlı; Linux'ta DejaVu yolu |
| Content.docx çıktısı garip | Settings'ten `content_prompt.md`'i edit et, kuralları sıkılaştır |
| LLM output 200 char aştı | Text alanını manuel kısalt — uyarı engellemiyor sadece bildiriyor |
| `Drive klasöründe 'X' zaten var` | Drive'dan eskisini sil veya yeniden adlandır, sonra tekrar üret |
| Drive cache eski veriyi gösteriyor | Settings → 🔄 Cache temizle |
| Combobox seçimi yapıştırınca dönüyor | text_input'a yapıştır + dışarı tıkla; geçerli isim listede yoksa öneriler görünür |

---

## Geliştirme notları

- **Sırlar git'e gitmesin:** `.env`, `google_oauth_client.json`, `.drive_token.pickle`, `app_config.json` gitignore'da
- **Repo:** https://github.com/ozguraltuntas/canva-automation
- **Test verisi:** `inputs/`, `masks/`, `outputs/` runtime, repo'da boş tutulur (`.gitkeep`)
- **PhotoRoom kotası:** dashboard veya `/v2/account` curl
- **Prompt edit:** Settings → content_prompt.md edit + save
- **Streamlit version:** 1.57+ (`@st.fragment` ve `selectbox.accept_new_options` için)
- **2 Chrome sekmesi** ile Vehicle ve Content paralel çalıştırılabilir (her sekme ayrı session_state)
