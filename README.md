# Hisse Haber Merkezi

BIST hisselerinin haberlerini hisse koduna göre toplayan, kendi
bilgisayarında/sunucunda çalışan bağımsız bir araç. PULSE mimarisiyle
uyumlu inşa edildi — detay: `PULSE_INTEGRATION_CONTRACT.md`.

## Mimari — doğru ifadeyle

**Ağ çağrıları yalnızca `haber/sources/` altında yapılır; `api.py` ağ
kütüphanesini import bile edemez.**

(Önceki sürümde bu "collector.py ağa çıkan tek dosya" diye yazılmıştı —
literal olarak yanlıştı, ağ çağrıları adaptörlerde. Kural artık bir
testle *zorunlu*: `haber/` altındaki herhangi bir dosya `requests`,
`httpx`, `feedparser` vb. import ederse ve `sources/` altında değilse,
test kırılır.)

```
sources/*.py (ağ) ──► collector.py ──► data/raw/       ham yanıtlar, asla üzerine yazılmaz
                                       data/store/     news.jsonl + collector_state.json
                                            │
                                            ▼ (salt-okunur)
                                       api.py ──► web/index.html
```

Process sınırı: collector ağa çıkar, API çıkmaz. Dosya sınırı: ağ
kütüphaneleri sadece adaptör katmanında.

## Kurulum

```bash
pip install -r requirements.txt
```

Sürümler sabitlenmiştir (`fastapi==0.141.1` gibi) — sunucuya taşırken
sürüm sürprizi olmasın diye.

### Sembol evreni — bunu atlama

`data/universe.txt` şu an **sadece 12 sembollük bir örnek**. Gerçek
kullanım için PULSE'un tam evrenini kopyala:

```
bist_sinyal_botu/vendor_acceptance/full_universe_593.txt
    →  hisse_haber_merkezi/data/universe.txt
```

> **Neden önemli:** bu dosyada olmayan bir sembol, RSS haberlerinde
> **tanınmaz** (fail-closed). 12 sembollük örnekle çalışırsan geri kalan
> 581 hissenin haberi hiç eşleşmez. KAP kayıtları bundan etkilenmez —
> sembolü yapısal alanda verir.

## Çalıştırma

**1) Haberleri topla** (ağa çıkan kısım):
```bash
python -m haber.collector              # bir kez
python -m haber.collector --loop 300   # her 5 dakikada bir
```

**2) Arayüzü başlat** (ayrı terminal):
```bash
uvicorn haber.api:app --host 127.0.0.1 --port 8000
```
Tarayıcı: `http://127.0.0.1:8000`

Arama kutusuna `ESCOM` yazıp Enter'a bas. Sağ üstteki **↻** ile
yenilenir; "Otomatik yenile" açılırsa 60 saniyede bir kendi kendine
günceller.

## Kaynaklar

| Kaynak | Tür | Ticker eşleşmesi |
|---|---|---|
| KAP | `REGULATORY` | **EXACT** — sembolü yapısal alanda verir |
| Bigpara, Mynet Finans, Bloomberg HT, Dünya | `MEDIA` | `INFERRED` — başlık/özet metninden çıkarım |

Arayüz bu ikisini ayrı rozetlerle gösterir; çıkarım yoluyla eşleşenlerde
"çıkarım" etiketi görünür.

**Kaynak eklemek/çıkarmak:** `data/sources.json` (yoksa
`haber/config.py::write_default_config()` ile oluşturulur). Kod
değiştirmen gerekmez.

**Yeni bir kaynak türü eklemek:** `haber/sources/` altına `NewsSource`
arayüzünü uygulayan tek bir dosya. Collector, store, API ve arayüz
değişmez.

## Uygulama gibi kullanma

### Tek tıkla başlatma

`basla.bat` — çift tıkla. Toplayıcıyı (5 dakikada bir) ve arayüz
sunucusunu ayrı pencerelerde başlatır, tarayıcıyı açar. Kapatmak için o
iki pencereyi kapat.

### Tarayıcıdan "uygulama olarak yükle"

Chrome/Edge adres çubuğunun sağındaki **yükle** ikonuna bas (ya da
menü → "Uygulamayı yükle"). Kendi penceresi, kendi ikonu olur; adres
çubuğu görünmez, masaüstüne/başlat menüsüne kısayol gelir.

> **Önbellek bilerek yok.** Service worker sadece "yüklenebilir uygulama"
> olmak için var; hiçbir şeyi önbelleğe almıyor. Bu bir haber aracı —
> önbellek demek bayat haber demek. Bir test bunu zorluyor.

### Telefondan (aynı Wi-Fi)

`basla_agda.bat` — sunucuyu ağa açar ve bilgisayarın IP adresini yazdırır.
Telefonun tarayıcısına `http://<o-adres>:8000` yaz.

İki not:
- Windows Güvenlik Duvarı ilk seferde izin sorar → **"Özel ağlar"** için izin ver
- Android'de "Ana ekrana ekle" çalışır ama **tam PWA kurulumu olmaz** —
  tarayıcılar HTTPS ya da `localhost` dışında service worker'a izin
  vermiyor. Yerel IP `http://` olduğu için kısayol seviyesinde kalır.
  Fonksiyon olarak fark yok, sadece "gerçek uygulama" hissi biraz eksik.

**Ve en önemlisi:** bunların hiçbiri PC'n kapalıyken çalışmaz. Telefondan
erişim de aynı ağda ve PC açıkken geçerli.

## İzleme listeleri (sekmeler)

Kendi hisse listelerini oluşturup sekme olarak gezebilirsin — örneğin bir
liste BOLT, bir liste AEGIS, bir liste genel izleme.

- **`+ liste`** sekmesine tıkla → ad ver, hisse kodlarını virgülle yaz
- Bir listeye tıkla → sadece o hisselerin haberleri
- Bir listeye **çift tıkla** → düzenle veya sil
- **Tüm haberler** sekmesi → filtresiz akış

Kaynak filtreleri (KAP / medya) listelerle birlikte çalışır: örneğin
"BOLT sekmesi + Sadece KAP" = sadece BOLT hisselerinin resmi bildirimleri.

Listeler **sunucuda ortak bir dosyada tutulmaz**. Her tarayıcı kendi
listelerini `localStorage` içinde saklar. Böylece public deploy'da başka bir
ziyaretçi senin BOLT/AEGIS listeni göremez veya silemez. Aynı kişinin farklı
cihaz/tarayıcıdaki listeleri de birbirinden bağımsızdır.

`data/universe.txt` varsa, evrende olmayan bir kod **reddedilir** — yazım
hatasıyla hiçbir zaman eşleşmeyecek bir liste oluşturmanı engeller. Liste
filtresi API'ye yalnızca ilgili sembolleri `tickers=` parametresiyle yollar;
API'de watchlist oluşturma/silme endpoint'i yoktur.

## Dayanıklılık davranışları

### Tek-instance kilidi

Task Scheduler'a bağlarsan, bir çalıştırma uzarsa bir sonraki tetikleme
üstüne binebilir. İki collector aynı anda çalışırsa aynı haber iki kez
yazılabilir ve state dosyası birbirinin üzerine yazılır. Bu yüzden
collector otomatik olarak `data/collector.lock` alır.

- İkinci örnek başlarsa: açık mesaj + **çıkış kodu 3** (zamanlayıcı
  bunu "hata" değil "zaten çalışıyor" diye ayırt edebilsin)
- Süreç çökerse kilit dosyası kalır → 30 dakika sonra **bayat** sayılır
  ve devralınır (uyararak). Yoksa araç kalıcı olarak kilitlenirdi.
- `--no-lock` ile atlanabilir (önerilmez)

### Ham yanıt önce korunur, doğrulama sonra

Bir kaynak HTTP 500 dönse veya "RSS diye HTML" gönderse bile, **gövde
diske yazılır** — `data/raw/FAILED_*.raw` olarak. Tam hata anındaki
kanıt en çok ihtiyaç duyulan şeydir; önceki sürümde bu atılıyordu.

### Boş yanıtın *nedeni* kayıtlıdır

`feed_status` alanı dört durumu ayırır — hepsini "başarılı ama boş"
saymak, bozuk bir kaynağı sessizce sağlıklı göstermek olurdu:

| Durum | Anlamı |
|---|---|
| `VALID_NONEMPTY` | geçerli akış, kayıt var |
| `EXPECTED_EMPTY` | geçerli akış, gerçekten boş (meşru) |
| `UNPARSEABLE` | HTML/bozuk geldi — bu bir akış değil |
| `EMPTY_SUSPECT` | boş + yapı doğrulanamadı |

### Provenance zinciri

`news.jsonl`'deki her kayıt, kendisini üreten ham dosyayı `raw_ref`
alanında taşır. Yani "bu haber tam olarak hangi yanıttan geldi?"
sorusunun cevabı vardır.

### Veri saklama — 7 gün

Bu araç **günlük/anlık haber takibi** için; tarihsel arşiv tutmuyor.
Her toplamadan sonra 7 günden eski veriler otomatik siliniyor.

```bash
python -m haber.collector --retention-days 14   # pencereyi değiştir
python -m haber.collector --no-prune            # bu turda budama yapma
```

**Haber kayıtları ve ham dosyalar aynı pencereyle budanır** — ayrı
olsalardı bir kaydın `raw_ref` alanı silinmiş bir dosyayı işaret eder,
provenance zinciri sessizce kırılırdı.

İki küçük tasarım kararı:
- Budama `collected_at` (bizim topladığımız an) üzerinden yapılır,
  `published_at` üzerinden değil — ikincisi kaynak beyanıdır, boş
  olabilir veya eski bir haber yeniden yayımlanabilir.
- Zaman damgası okunamayan kayıt **silinmez** (silmek geri alınamaz,
  saklamak zararsız).

> İleride PULSE'a entegre edilirse bu pencere yeniden değerlendirilmeli —
> 7 günlük veriyle tarihsel analiz yapılamaz. Entegrasyon sözleşmesinde
> not düşülü.

### Gürültü azaltma

**KAP rutin bildirimleri varsayılan gizli.** "Pay Bazında Devre Kesici",
"Piyasa Yapıcılığı" gibi yüksek hacimli/düşük bilgili bildirim *türleri*
`ROUTINE` olarak sınıflanır. `Rutin KAP` çipiyle görünür yapılabilir.

> Bu bir değer yargısı **değil** — bildirimin *türünü* sınıflar, hissenin
> iyi/kötü oluşu hakkında hiçbir şey söylemez. `sentiment` alanından farkı
> budur; NEWS ≠ SIGNAL sınırına dokunmaz.

### Şirket adı eşlemesi

Haber metinleri çoğu zaman sembol yazmaz: *"Garanti Bankası kârını
açıkladı"* cümlesinde GARAN geçmez. `data/company_aliases.json` bu boşluğu
kapatır (93 eşleme). Kendin ekleyebilirsin — kısa/genel adlardan kaçın,
yanlış pozitif kaçırılan haberden kötüdür.

Alias eşleşmesi yine `INFERRED` sayılır, `EXACT` değil.

### "Yeni" işareti

Son bakışından sonra gelen haberler mavi kenarlık + `yeni` rozetiyle
görünür. Sayfadan ayrılınca okundu sayılır (tarayıcıda saklanır).

## Bilerek yapılmayanlar

- **Twitter/X:** API artık ücretli (temel seviye ~100 USD/ay), scraping
  ToS ihlali. Adaptör yuvası (`SOURCE_KIND_SOCIAL`) hazır, uygulama yok.
  Ödemeye karar verilirse tek dosya eklemekle çalışır.
- **Tam makale metni saklamak:** Telif. Başlık + kaynağın kendi verdiği
  kısa özet (en fazla 500 karakter) + link tutulur; tam metin için
  kaynağa gidilir.
- **Sinyal/tavsiye üretmek:** `NEWS != SIGNAL`. Bkz. entegrasyon
  sözleşmesi §2.

## Sağlık paneli — `freshness` ≠ `completeness`

Arayüzün üstündeki panel bu ikisini **ayrı** gösterir, çünkü aynı şey
değiller:

- **Taze ama eksik:** 2 dakika önce başarıyla çekildi, ama 5 kaynaktan
  2'si hata verdi.
- **Tam ama bayat:** tüm kaynaklar çalışıyor, ama son çekim 3 saat önce.

Tek bir "yeşil nokta" bu ayrımı gizlerdi.

## İlk çalıştırmada sorun çıkarsa

**Tek kritik nokta KAP'tır.** KAP'ın public uç noktası ve JSON alan
adları zamanla değişebilir. Adaptör bunu sessizce boş dönmek yerine
**açık hata** olarak bildirir (sağlık panelinde görünür). Böyle bir
durumda düzeltilecek tek yer: `haber/sources/kap.py::_extract_records()`
ve `_parse_records` içindeki alan adları. Uç nokta `data/sources.json`
üzerinden değiştirilebilir.

RSS adresleri de yayıncılar tarafından değiştirilebilir — sağlık
panelinde hangi kaynağın düştüğü görünür.

## Test

```bash
python -m pytest tests/ -q
```

87 test; contract doğrulama, ticker çıkarımı (fail-closed dahil), RSS/KAP
ayrıştırma, store idempotency + raw-preservation, health'in
freshness/completeness ayrımı, ve iki mimari garanti:
API'nin ağ kütüphanesi import etmediği, contract'ta sinyal/tavsiye alanı
bulunmadığı, API'nin veri deposuna yazmadığı, ve ağ kütüphanelerinin
sadece `sources/` katmanında kullanıldığı.
