# PULSE Entegrasyon Sözleşmesi — Hisse Haber Merkezi

## HISSE_HABER_MERKEZI — CANONICAL FUTURE INTEGRATION OPTION

> Çalışan, bağımsız kişisel haber takip aracı. PULSE'a şu an bağlı değil
> ve ana roadmap'i etkilemiyor. Ancak ileride **PULSE AI / NewsContext /
> Trade Forensics / event-context research / live market-context**
> aşamalarında entegrasyon adayı olarak yeniden değerlendirilecek.
> `NEWS ≠ SIGNAL` ve PULSE read-only consumer sınırı korunacak.

**Statü:** `CANONICAL_FUTURE_INTEGRATION_OPTION`
**Ana roadmap etkisi:** yok — PULSE'un mevcut faz sırasını değiştirmez
**Yeniden değerlendirme tetikleyicisi:** yukarıdaki beş aşamadan biri gündeme geldiğinde

---

**Durum:** Tasarım kaydı. Entegrasyon **henüz yapılmadı** ve bu araç PULSE'a
bağımlı değildir — bağımsız çalışır. Bu doküman, ileride entegrasyon
istendiğinde *nereden* bağlanacağını ve hangi sınırların korunacağını
önceden sabitler.

---

## 1. Neden bu mimari

Bu araç bilerek PULSE'un kendi ilkeleriyle inşa edildi, böylece ileride
"yapıştırma" değil **yerleştirme** olur:

| PULSE ilkesi | Bu araçtaki karşılığı |
|---|---|
| Collector = writer, PULSE = read-only consumer, PULSE ağa çıkmaz | `haber/collector.py` ağa çıkan tek bileşen; `haber/api.py` ağ kütüphanesini **import bile etmez** (test ile garanti) |
| Versiyonlu veri sözleşmesi | `NEWS_CONTRACT_V1` — şema sessizce değişmez, değişirse V2 olur |
| Raw preservation, asla üzerine yazma | `data/raw/` — her çekim benzersiz dosya |
| Idempotent yazma | `item_id` deterministik; aynı haber ikinci kez yazılmaz |
| Fail-soft containment | Bir kaynak çökünce diğerleri durmaz |
| Fail-closed doğrulama | Contract ihlali eden kayıt sessizce kabul edilmez, sayılır |
| Freshness ≠ completeness | `haber/health.py` ikisini **ayrı** raporlar |
| Vendor-agnostic adaptör | `NewsSource` arayüzü; yeni kaynak = tek dosya |
| Provenance | Her kayıt hangi kaynaktan, ne zaman, hangi ham yanıttan geldiğini taşır |

---

## 2. En kritik sınır: NEWS ≠ SIGNAL

PULSE'un `SIGNAL != ORDER` ayrımının buradaki karşılığı:

> **Bu araç haber üretir, sinyal üretmez.**

`NewsItem` içinde yön, skor, tavsiye, hedef fiyat, duygu (sentiment)
alanı **yoktur** — ve bunların eklenmediği bir test tarafından sürekli
doğrulanır (`test_contract_has_no_signal_or_recommendation_field`).

Sebep: haber katmanı sessizce bir strateji katmanına dönüşürse, PULSE'un
tüm ön-kayıtlı (preregistered) araştırma disiplini arkadan dolanılmış
olur. Haber, olsa olsa bir `PulseSignal`'in **`reason_codes` / `signal_metadata`**
girdisi olabilir — sinyalin kendisi asla.

### Sentiment / yorum — nerede yapılır, nereye yazılmaz

Karar (PO ile mutabık): **yorumu PULSE yapar.** Bir haberin olumlu/olumsuz/
nötr oluşunu değerlendirmek meşrudur ve bunun için ek veri toplamaya gerek
yoktur — dil modeli bunu başlıktan zaten çıkarır.

Ama kritik sınır konumda değil, **kalıcılıkta**:

| | Nerede | Kabul |
|---|---|---|
| Okuma anında üretilen yorum (PULSE gösteriminde rozet) | Contract'ın dışında | ✅ |
| `news.jsonl` içine yazılan `sentiment` alanı | Contract'ın içinde | ❌ |

Gerekçe: kayda yazılan bir etiket, sonradan okuyan için **olgu gibi**
görünür ve sessizce veri olarak akar. Okuma anında üretilen yorum ise
yorumu yapanın sorumluluğunda kalır — ve aynı haberi yarın farklı
değerlendirebilmek mümkün olur, ki doğrusu budur.

`NewsItem` üzerinde `sentiment`/`score`/`direction` gibi alanların
bulunmadığı bir testle sürekli doğrulanır
(`test_contract_has_no_signal_or_recommendation_field`).

---

## 3. Entegrasyon noktası (ileride)

PULSE roadmap'inde bu, **Platform Hardening** fazındaki `PulseSignal`
contract'ı devreye girdikten *sonra* anlamlı olur. Önerilen bağlantı:

```
Hisse Haber Merkezi (bağımsız process)
        │  data/store/news.jsonl  (dosya, salt-okunur)
        ▼
PULSE read-only consumer  →  NewsContext  →  PulseSignal.signal_metadata
                                              PulseSignal.reason_codes
```

**Bağlantı dosya üzerinden olmalı, HTTP ile değil** — PULSE'un "hiçbir
koşulda network'e çıkmaz, sadece local status dosyası okur" kuralı
gereği. Yani PULSE `news.jsonl`'i doğrudan okur; bu aracın API'sine
istek atmaz.

### Entegrasyondan önce çözülmesi gerekenler

1. **Zaman hizalaması.** `published_at` bazı kaynaklarda `None`. PULSE
   tarafında bir haberi bir bar'a bağlamak için **kesin** bir zaman
   gerekir. Zamanı bilinmeyen haber, bar'a bağlanmamalı (fail-closed).
2. **Look-ahead riski.** Bir haberin `collected_at`'i, `published_at`'inden
   sonradır. Geriye dönük analizde **`published_at`** kullanılmalı, ama
   o da yayıncının beyanıdır — RSS yayıncıları tarihi geriye dönük
   düzeltebilir. Backtest'te haber kullanılacaksa bu, PULSE'un
   `DATA_VALIDITY_POLICY` seviyesinde ayrıca ele alınmalı.
3. **`INFERRED` eşleşmeler.** Metinden çıkarılan ticker'lar yanlış
   olabilir. PULSE tarafında varsayılan olarak **sadece `EXACT`**
   (KAP) kullanılması, `INFERRED`'in ancak açıkça istendiğinde
   katılması önerilir.
4. **Tarihsel derinlik yok — üstelik 7 günle sınırlı.** Bu araç ileriye
   dönük toplar ve `RETENTION_POLICY_V1` gereği 7 günden eski veriyi
   siler (günlük takip amaçlı). PULSE backtest'inde haber kullanılacaksa
   bu pencere **önceden** genişletilmiş olmalı; geriye dönük
   genişletilemez, silinen veri geri gelmez. Yani bir OOS backtest'inde haber kullanmak,
   ancak toplama başladıktan sonraki dönem için mümkündür.

---

## 4. Değişmez kurallar

- Bu araç PULSE'un `engine/`, `backtest/`, `data/` modüllerini **import etmez**.
- PULSE bu aracın kodunu **import etmez** — sadece çıktı dosyasını okur.
- Contract değişirse `NEWS_CONTRACT_V2` olur; V1 okuyucuları kırılmaz.
- Tam makale metni **saklanmaz** (telif). Başlık + kısa özet + link.
