# Hybrid RAG Uyum Denetçisi — Tasarım Dokümanı

Tarih: 2026-10-12
Durum: Gözden geçirme bekliyor

## 1. Amaç

Upwork portfolyosu için, sözleşmeleri bir kural setine göre denetleyen ve her bulguyu kaynak metne bağlayan bir RAG sistemi.

Hedef müşteri mesajı: somut bir alanda (sözleşme denetimi) uçtan uca çalışan ürün, altında ölçülmüş ve alandan bağımsız mühendislik.

### Başarı ölçütleri

- Bir PDF sözleşme yüklenip bir playbook'a göre denetlenebiliyor; rapordaki her alıntı kaynak metinde birebir bulunuyor ve PDF'te işaretlenebiliyor.
- README'de gerçek ölçümden üretilmiş benchmark tablosu var: arama konfigürasyonları ve bulut vs yerel model karşılaştırması.
- Kural seti değiştirilerek (ikinci playbook) aynı sistem başka bir alanda çalışıyor.
- Sistem `docker compose up` ile ayağa kalkıyor.
- Yerel modda (Ollama) hiçbir veri makineden çıkmıyor.

### Kapsam dışı

- Herkese açık canlı demo, ziyaretçi limitleri, kota.
- Taranmış PDF'ler için OCR (sistem algılar ve anlaşılır hata verir).
- Sorgudan otomatik metadata filtresi çıkarma.
- CrewAI, Elasticsearch, React arayüz.
- Chroma adaptörü (depo arayüzü buna izin verir, şimdilik yazılmıyor).
- Kullanıcı hesapları ve yetkilendirme.

## 2. Mimari

Üç katman: çekirdek kütüphane → FastAPI → Streamlit. Arayüz yalnızca API'yi çağırır.

```
Streamlit UI
     │ HTTP
FastAPI
     │
Çekirdek kütüphane (auditor)
 ├─ ingestion   PDF → chunk + metadata
 ├─ index       embedding, vektör deposu arayüzü, Qdrant
 ├─ retrieval   filtre → hybrid → RRF → rerank → parent
 ├─ llm         sağlayıcı arayüzü: Anthropic | Ollama
 ├─ audit       playbook, LangGraph grafı, alıntı doğrulama, puanlama
 ├─ qa          belgeye sor
 └─ storage     SQLite: denetimler, izler, inceleme kararları
```

### Teknoloji seçimleri

| Konu | Seçim |
|---|---|
| Vektör deposu | Qdrant (dense + sparse aynı koleksiyonda) |
| Dense embedding | `BAAI/bge-m3` (çok dilli) |
| Sparse | BM25 (Qdrant sparse vektör) |
| Reranker | `BAAI/bge-reranker-v2-m3` |
| Orkestrasyon | LangGraph |
| Bulut LLM | Claude: değerlendirme `claude-sonnet-5-5`, yardımcı işler `claude-haiku-5-5` |
| Yerel LLM | Ollama, JSON şema kısıtlı çıktı |
| PDF ayrıştırma | PyMuPDF |
| API | FastAPI |
| Arayüz | Streamlit |
| Kayıt deposu | SQLite |
| Paketleme | Docker Compose (uygulama, Qdrant, isteğe bağlı Ollama) |

### Donanım

Geliştirme ve benchmark makinesi: RTX 3060 12 GB, 16 GB RAM. Embedding (~2 GB), reranker (~2 GB) ve 8B sınıfı yerel LLM (~5–6 GB) birlikte sığar. 14B sınıfı model denenirken reranker CPU'da çalışır.

### Proje yapısı

```
src/auditor/
  ingestion/   parser.py, structure.py, chunker.py, metadata.py
  index/       store.py (arayüz), qdrant_store.py, embedder.py
  retrieval/   config.py, pipeline.py, fusion.py, reranker.py
  llm/         base.py, anthropic_provider.py, ollama_provider.py
  audit/       playbook.py, graph.py, nodes.py, citations.py, scoring.py, report.py
  qa/          answer.py
  storage/     db.py
  api/         main.py, routes/
ui/            Streamlit sayfaları
playbooks/     commercial_contract.yaml, gdpr_dpa.yaml
benchmarks/    retrieval_bench.py, audit_bench.py, make_readme_table.py, results/
tests/
docker-compose.yml
```

## 3. Ingestion ve indeksleme

Akış: PDF → ayrıştırma → yapı tespiti → chunk'lar → metadata → indeks.

- **Ayrıştırma:** PyMuPDF ile her metin bloğu sayfa numarası ve bbox koordinatıyla alınır. Metin katmanı olmayan belge reddedilir: "Bu belge taranmış, metin katmanı yok."
- **Yapı tespiti:** Madde numaralandırması (`1.`, `1.1`, `Section 5`, `ARTICLE IV`) ve yazı boyutu ipuçlarından bölüm ağacı çıkarılır. Yapı bulunamazsa paragraf bazlı bölmeye düşülür.
- **Parent-child chunk:**
  - Child: madde veya alt madde, en fazla 400 token. Daha uzun madde cümle sınırından bölünür.
  - Parent: child'ın ait olduğu üst bölüm, en fazla 2000 token. Daha uzunsa en yakın alt bölüm parent olur.
  - Arama child üzerinde yapılır, LLM'e parent verilir.
- **Chunk metadata:** `document_id`, `chunk_id`, `parent_id`, `page_number` (liste), `section_title`, `section_path` (örn. `8 > 8.2`), `bboxes`, `char_start`, `char_end`.
- **Belge metadata:** `doc_type`, `date`, `parties`, `jurisdiction`. Belge başına bir kez, ilk sayfalardan küçük modelle şemaya bağlı çıkarılır. Çıkarılamayan alan boş kalır.
- **Bağlam öneki:** Açılıp kapatılabilir. Açıkken embedding'den önce her chunk'a tek cümlelik belge bağlamı eklenir. Varsayılan kapalı; benchmark sonucuna göre değiştirilir.
- **İndeks:** Tek Qdrant koleksiyonu; chunk başına bir dense ve bir sparse vektör. `document_id`, `doc_type`, `date`, `jurisdiction` alanları filtre için indekslenir.
- **Tekrar yükleme:** Belge içerik SHA-256 hash'iyle tanınır; aynı dosya ikinci kez indekslenmez.
- **Düz metin girişi:** Chunker düz metinle de çalışır (bbox olmadan). Benchmark bu yolu kullanır.

## 4. Arama hattı

Akış: sorgu → metadata filtresi → hybrid arama → RRF → rerank → parent genişletme.

1. **Filtre:** Belge, belge türü, tarih aralığı, yargı bölgesi. Aramadan önce uygulanır.
2. **Hybrid arama:** BM25 ve dense ayrı ayrı ilk 30 sonucu getirir.
3. **RRF:** İki liste sıra numaralarına göre birleştirilir.
4. **Rerank:** İlk 30 aday cross-encoder ile puanlanır, ilk 5 kalır.
5. **Parent genişletme:** Kalan chunk'ların parent'ları getirilir, tekilleştirilir.

### Kararlar

- **Aşama skorları kaydedilir:** her sonuç için BM25 sırası, dense skoru, RRF skoru, rerank skoru, sıra değişimi.
- **Tek ayar nesnesi (`RetrievalConfig`):** `mode` (`bm25` | `dense` | `hybrid`), `rerank` (açık/kapalı), `candidate_k` (30), `final_k` (5). Benchmark aynı kodu aynı nesneyle çalıştırır.
- **Yetersiz kanıt sinyali:** En iyi sonucun rerank skoru eşiğin altındaysa sonuç `insufficient_evidence=true` ile döner. Eşik benchmark verisinden ayarlanır ve config'de tutulur.
- **Depo arayüzü (`VectorStore`):** Arama kodu Qdrant'a doğrudan bağlı değildir.

## 5. Denetim ajanı

### Playbook

Her playbook bir YAML dosyasıdır; yüklenirken şemaya göre doğrulanır.

```yaml
name: Ticari sözleşme
rules:
  - id: liability_cap
    title: Sorumluluk üst sınırı
    type: must_exist          # must_exist | must_not_exist | condition
    severity: high            # low | medium | high
    queries: ["limitation of liability", "liability cap aggregate amount"]
    criteria: "Toplam sorumluluk belirli bir tutar veya formülle sınırlanmış olmalı."
```

### Durumlar

| Kural türü | Madde bulundu, ölçütü karşılıyor | Madde bulundu, karşılamıyor | Madde bulunamadı |
|---|---|---|---|
| `must_exist` | uyumlu | uyumsuz | eksik |
| `condition` | uyumlu | uyumsuz | eksik |
| `must_not_exist` | uyumsuz (madde var) | — | uyumlu |

Ek durumlar: `belirsiz` (alıntı doğrulanamadı, insan incelemesi gerekir), `hata` (LLM çağrısı başarısız).

### Graf

Her kural için aynı akış çalışır; kurallar eşzamanlılık sınırıyla paralel işlenir.

1. **Ara:** Kuralın sorgularıyla, yalnızca denetlenen belgede.
2. **Kanıt yeterli mi?** `insufficient_evidence` ise küçük model sorguyu yeniden yazar ve arama tekrarlanır. En fazla 2 tekrar.
3. **Değerlendir:** Güçlü model kuralı ve parent bölümleri alır; şemaya bağlı çıktı üretir: durum, gerekçe, birebir alıntılar.
4. **Geniş tarama:** Yokluk hükmü verilen her durumda (`eksik`, veya `must_not_exist` için `uyumlu`) çalışır. İlk 15 aday bölüm küçük modelle tek tek "bu bölüm kuralla ilgili mi?" diye kontrol edilir. İlgili bölüm çıkarsa değerlendirme o bölümle tekrarlanır.
5. **Alıntıyı doğrula:** Her alıntı, boşluk ve tırnak karakterleri normalize edilerek kaynak metinde tam eşleşmeyle aranır. Bulunamayan alıntı atılır. Bir madde bulunduğunu iddia eden bulguda doğrulanmış alıntı kalmazsa değerlendirme bir kez tekrarlanır; yine kalmazsa durum `belirsiz` olur. Doğrulanan alıntı karakter ofsetleri üzerinden sayfa ve bbox'a bağlanır.
6. **Raporla:** Bulgular tek JSON raporda toplanır.

Yokluk bulgusu neye dayandığını raporda söyler: denenen sorgu sayısı ve incelenen bölüm sayısı.

### Risk puanı

LLM yalnızca durumu belirler; puanı kod hesaplar.

- Önem ağırlığı: `low`=1, `medium`=2, `high`=3.
- Durum çarpanı: uyumlu=0, belirsiz=0.5, uyumsuz=1, eksik=1.
- Kural riski = ağırlık × çarpan.
- Belge risk puanı = 100 × Σ(kural riski) / Σ(ağırlık). 0 risksiz, 100 en yüksek risk.
- `hata` durumundaki kurallar hesaba katılmaz ve raporda ayrıca listelenir.

### Rapor

```json
{
  "audit_id": "…",
  "document_id": "…",
  "playbook": "commercial_contract",
  "provider": "anthropic",
  "model": "claude-sonnet-5-5",
  "risk_score": 37.5,
  "cached": false,
  "findings": [
    {
      "rule_id": "liability_cap",
      "title": "Sorumluluk üst sınırı",
      "status": "uyumlu",
      "severity": "high",
      "risk": 0,
      "reasoning": "…",
      "citations": [
        {"quote": "…", "page": 14, "section_path": "9 > 9.2", "bboxes": [[72, 310, 523, 348]]}
      ],
      "evidence": {"queries_tried": 2, "sections_examined": 5},
      "review": null
    }
  ],
  "errors": [],
  "totals": {"duration_s": 38.2, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
}
```

### İz kaydı

Her düğüm girdi özeti, çıktı, süre, token sayısı ve maliyet kaydeder. Kayıt denetimle birlikte SQLite'a yazılır.

### Önbellek

Anahtar: `sha256(belge hash + playbook hash + sağlayıcı + model + prompt sürümü)`. Kayıt varsa rapor ve iz oradan döner, `cached=true` olur. Arayüzde yeniden çalıştırmayı zorlayan bir seçenek bulunur.

### Modeller

- Bulut: değerlendirme `claude-sonnet-5-5`; sorgu yeniden yazma, geniş tarama, metadata çıkarma ve belgeye sor `claude-haiku-5-5`.
- Yerel: tüm işler tek Ollama modeliyle. Model adı config'den okunur (`OLLAMA_MODEL`). Varsayılan, uygulama sırasında 8B sınıfı adaylar 5 örnek kuralda denenip şemaya en tutarlı uyan seçilerek belirlenir; 14B sınıfı bir model benchmark'ta ek satırdır.

### Hata yönetimi

- LLM çağrısı veya şema doğrulaması başarısız olursa bir kez tekrar denenir; sonra kural `hata` olur, denetim devam eder.
- Ollama'ya ulaşılamazsa denetim başlamadan anlaşılır hata döner.
- Playbook şemaya uymuyorsa yükleme hatası hangi kuralın hangi alanının hatalı olduğunu söyler.

## 6. Belgeye sor

1. Arama hattı sorguyla çalışır (seçili filtrelerle).
2. `insufficient_evidence` ise LLM çağrılmaz; "Bu belgelerde buna dair bir ifade bulamadım" mesajı ve en yakın pasajlar döner.
3. Değilse küçük model parent bölümlerden alıntılı cevap üretir.
4. Alıntılar denetimdekiyle aynı doğrulayıcıdan geçer. Doğrulanmış alıntı kalmazsa cevap gösterilmez, 2. adımdaki mesaj döner.

## 7. API

| Uç nokta | İş |
|---|---|
| `POST /documents` | PDF yükle ve indeksle |
| `GET /documents` | Belgeleri ve metadata'yı listele |
| `GET /documents/{id}/file` | PDF dosyası |
| `POST /search` | Arama; aşama skorlarıyla sonuç |
| `POST /ask` | Belgeye sor |
| `GET /playbooks` | Playbook listesi |
| `POST /audits` | Denetim başlat (belge, playbook, sağlayıcı) |
| `GET /audits/{id}` | Rapor |
| `GET /audits/{id}/trace` | Ajan izi |
| `POST /audits/{id}/findings/{rule_id}/review` | Kabul/ret ve not |
| `GET /audits/{id}/export?format=json\|pdf` | Dışa aktarma |
| `GET /benchmarks` | Kayıtlı benchmark sonuçları |

## 8. Arayüz

Streamlit, altı sayfa:

1. **Belgeler:** yükleme, indeksleme durumu, metadata.
2. **Arama:** sorgu, filtreler, mod seçimi; aşama skorları ve sıra değişimi tablosu; sonuca tıklayınca PDF'te işaretleme.
3. **Belgeye sor:** alıntılı cevap veya "bulamadım".
4. **Denetim:** belge, playbook, model seçimi; bulgu listesi (durum, risk, alıntı); PDF'te işaretleme; kabul/ret ve not; JSON/PDF dışa aktarma; önbellekten gelen sonuçta "kayıtlı çalıştırma" etiketi (tarih, model, süre, maliyet).
5. **Ajan izi:** kural başına düğüm zaman çizelgesi; süre, token, maliyet.
6. **Benchmark:** tablo ve grafikler.

**PDF işaretleme:** Önce bbox ile işaretlemeyi destekleyen hazır bir Streamlit PDF bileşeni denenir. Desteklemiyorsa PDF.js küçük bir özel Streamlit bileşeni olarak gömülür. İki yol da aynı veriyi kullanır: sayfa numarası ve bbox listesi.

## 9. Benchmark

Veri: CUAD (510 sözleşme, 41 madde türü, uzman işaretli metin aralıkları). Düz metin sürümü kullanılır.

### Arama ölçümü (tüm CUAD, LLM'siz)

İsabet: bulunan chunk, uzman işaretli aralıkla örtüşüyor. Ölçütler: recall@5, recall@30, MRR.

Satırlar:

- yalnız BM25
- yalnız dense
- hybrid
- hybrid + rerank
- yapısal chunking vs semantic chunking (hybrid + rerank üzerinde)
- bağlam öneki açık vs kapalı (chunk başına LLM çağrısı gerektirdiği için 50 sözleşmelik alt kümede)

### Denetim ölçümü (50 sözleşmelik sabit alt küme)

CUAD madde türleri `must_exist` kuralına çevrilir. CUAD bir sözleşmede bulunmayan madde türlerini de belirttiği için yokluk hükümleri ölçülebilir.

- Eksik madde tespiti: precision, recall, F1.
- Alıntı doğruluğu: alıntının uzman işaretiyle örtüşme oranı.
- Sağlayıcı satırları: Claude, yerel 8B, yerel 14B.
- Denetim başına ortalama süre ve maliyet.

### Çıktı

Sonuçlar `benchmarks/results/*.json` dosyalarına yazılır. README tablosu `make_readme_table.py` ile bu dosyalardan üretilir; rakamlar elle yazılmaz. Alt küme sözleşme listesi depoda sabit tutulur.

## 10. Playbook'lar

- `commercial_contract.yaml`: CUAD madde türlerinden türetilir; benchmark bunu kullanır.
- `gdpr_dpa.yaml`: GDPR veri işleme sözleşmesi kontrol listesi; sistemin alandan bağımsız olduğunu gösterir.

## 11. Testler

Geliştirme test önce (TDD) ilerler.

- **Birim (LLM'siz):** yapı tespiti, chunker (boyut sınırları, parent-child bağı, ofsetler), RRF, alıntı doğrulayıcı (normalizasyon, eşleşmeyen alıntı), risk puanı, playbook doğrulama, önbellek anahtarı.
- **Akış (sahte LLM):** denetim grafı; sorgu yeniden yazma döngüsü, geniş tarama, `belirsiz` ve `hata` yolları; belgeye sor'da kanıt yokken LLM çağrılmaması.
- **Entegrasyon:** küçük örnek PDF ve bellek içi Qdrant ile yükleme → arama → denetim → rapor.
- **API:** uç noktaların sözleşme testleri.

## 12. Teslim edilecekler

- `docker compose up` ile çalışan sistem.
- Mimari diyagramlı README; kurulum, bulut/yerel mod geçişi, yeni playbook yazma.
- Benchmark tablosu ve sonuç dosyaları.
- İki playbook.
- Video için çekim sırası.

## 13. Uygulama sırasında doğrulanacaklar

Her birinin yedek yolu tanımlıdır; hiçbiri tasarımı değiştirmez.

| Konu | Yedek yol |
|---|---|
| Qdrant'ta BM25 sparse vektör üretimi | `rank_bm25` ile sparse vektörü uygulamada üretmek |
| Hazır Streamlit PDF bileşeninin bbox desteği | PDF.js özel bileşeni |
| 8B modelin şemaya bağlı çıktıda tutarlılığı | Daha küçük bağlam ve kural başına tek alıntı sınırı |
| 12 GB VRAM'de üç modelin birlikte çalışması | Reranker'ı CPU'ya almak |
