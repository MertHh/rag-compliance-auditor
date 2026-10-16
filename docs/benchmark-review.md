# Yerel koşuların değerlendirmesi (ücretli koşudan önce)

Tarih: 2026-10-16. Bütün sayılar `benchmarks/results/*.json` dosyalarından alınmıştır. Bu belgedeki hiçbir koşuda OpenAI çağrısı yapılmadı, harcama $0'dır.

## Bulunan ve düzeltilen hatalar

| Belirti | Neden | Düzeltme |
|---|---|---|
| Gömülü Qdrant ile tam arama ölçümü ~20 saat sürecekti | Filtreli sorgu başına 0.5–1.1 s | Qdrant sunucusu (`QDRANT_URL`), varyant başına koleksiyon, atomik sıra önbelleği (`8dbc79f`) |
| Bağlam öneki, sağlayıcı kapalıyken yüklemeyi düşürüyordu | Yalnız `LLMError` yakalanıyordu | `ProviderUnavailableError` da yakalanıyor, hatalar sayılıyor (`8586d46`) |
| Ücretli denetim koşusu fiyatı olmayan modelle bütçe sınırı olmadan başlayabiliyordu | Fiyat kontrolü yoktu | Fiyatsız model reddediliyor; boş alt küme hata veriyor; hatalı denetimlerden devam ediliyor (`87e27fd`) |
| README tablosu çok satırlı hücrede bozuluyordu; okunamayan dosya sessizce atlanıyordu | Kaçış eksikti | Tek satır, bozuk dosyada hata satırı ve çıkış kodu 1 (`0299631`) |
| Docker'da Ollama'ya hiç ulaşılamıyordu | `.env.example`'daki `OLLAMA_HOST=localhost` konteynere geçiyordu | Compose artık `DOCKER_OLLAMA_HOST` okuyor (`efb2f77`) |
| Ctrl+C ile yarıda kalan indeksleme "tamamlandı" sayılıyordu | Qdrant'ta tek bir nokta olması yetiyordu | Parça sayısı kaydediliyor ve karşılaştırılıyor (`fa18140`) |
| 3 sözleşmelik deneme dosyası tam sonuç gibi görünüyordu | Dosya adı ve not kısmi koşuyu belirtmiyordu | `-firstN` adı ve "first N of 50" notu (`0befa02`) |
| AB sözleşmesinde 3 kural belirsiz çıktı, `ask` var olan maddeyi bulamadı | PDF satır sonunda bölünen kelimeler ("en-
sure", "con-
troller"); model kelimeyi bütün ya da "con- troller" diye kopyalıyor, alıntı doğrulanmıyordu | İki harf arasındaki tire eşleştirmede yok sayılıyor; alıntının özgün metni ve konumu korunuyor (`3ba7b5a`). Sonuç: 9/12 yerine 11/12 uyumlu |
| GDPR playbook'unda iki yanlış madde atfı | Art. 33(2)/33(1) ve Art. 28(10) karışmıştı | Atıflar düzeltildi (`4dee057`) |
| qwen3 düşünme moduyla denetim 8 kat yavaştı (1788 s'ye karşı 207 s) | Modelin varsayılanı düşünmek | `OLLAMA_THINK=0` varsayılan (`26a120b`) |
| 16k bağlamla 8B model ekran kartına sığmıyor, RAM doluyordu | Embedding ve reranker modelleri de aynı kartta | `OLLAMA_NUM_CTX=8192` (`4dee057`) |
| granite3.3:8b bir sözleşmede sonsuz üretime girdi (10 dk zaman aşımları) | Model davranışı | Aday karşılaştırmasında 4 sözleşmeyle puanlandı; seçilmedi |

## Spec bölüm 1 başarı ölçütleri

| Ölçüt | Durum | Kanıt |
|---|---|---|
| PDF denetimi ve alıntıların PDF'te işaretlenmesi | Tamam | Plan 3'te doğrulandı |
| Gerçek ölçümden üretilmiş benchmark tablosu | Yerel satırlar hazır | `benchmarks/results/`, README tabloları `make_readme_table` ile üretiliyor |
| İkinci playbook başka alanda çalışıyor | Tamam | AB Komisyonu'nun Art. 28 standart sözleşme maddeleri (2021/915 Eki) üzerinde `gdpr_dpa`: 12 kuralın 11'i uyumlu ve doğrulanmış alıntılı, risk 5.2, 157 s, $0. `processor_own_purposes` belirsiz: model maddeyi bulduğunu söyleyip alıntı vermedi |
| `docker compose up` | Tamam | İmaj derlendi; yükleme 12 chunk üretti; arayüz 200 döndü; belge `down`/`up` sonrası duruyor |
| Yerel modda veri makineden çıkmıyor | Tamam | `OPENAI_API_KEY` boşken `ask` sayfa 6'dan alıntıyla cevap veriyor ve `audit --force` $0 ile bitiyor; OpenAI çağrısı `OPENAI_API_KEY is not set` ile hemen düşüyor |

## Ölçüm özeti

| Ölçüm | Sonuç |
|---|---|
| Arama (100 sözleşme, 867 sorgu) | hybrid recall@5 0.820 / MRR 0.672; bm25 0.802 / 0.661; dense 0.739 / 0.585; hybrid + rerank 0.796 / 0.658 |
| Chunking | structural 0.796, semantic 0.792 (recall@5) |
| Bağlam öneki (50 sözleşme) | açık ve kapalı ikisi de 0.808 |
| Yalnız arama ile var/yok (aynı 850 çift, eşik başka sözleşmelerde seçildi) | F1 0.834, precision 0.746 |
| qwen3:8b denetim (50 sözleşme) | F1 0.875, precision 0.950, alıntı doğruluğu 0.782, 0 hata, 370 s/denetim |
| 8B adaylar (5 sözleşme) | qwen3:8b F1 0.895 / 0 hata; llama3.1:8b 0.545 / 4 hata; granite3.3:8b 0.293 / 8 hata |
| qwen3:14b ve qwen3:8b, aynı ilk 15 sözleşme | 14B: F1 0.877, precision 0.934, alıntı 0.781, 0 hata, 1584 s/denetim. 8B: F1 0.825, precision 0.925, alıntı 0.727, 0 hata, 389 s/denetim |
| OpenAI, ilk 15 sözleşme | gpt-5.4-mini: F1 0.752, precision 0.951, recall 0.622, alıntı 0.659, $0.117/denetim, toplam $1.76 |
| OpenAI, ilk 5 sözleşme | gpt-5.5 değerlendirici: F1 0.867, alıntı 0.594, $0.68/denetim, toplam $3.41. Aynı 5 sözleşmede mini 0.800, qwen3:8b 0.895, qwen3:14b 0.914 |

Yorum:
- Hybrid arama en iyisi. Sözleşme dili kalıplı olduğu için BM25, dense aramadan iyi sonuç veriyor.
- Reranker bu veride sıralamayı iyileştirmiyor. Puanı "kanıt yetersiz" sinyali olarak kullanıldığı için hattan çıkarılmadı. Eşik ölçümle 0.05'ten 0.005'e indi.
- Semantic chunking ve bağlam öneki ölçülebilir bir fark yaratmadı. İkisi de kapalı kalıyor, böylece yükleme hızlı ve ücretsiz kalıyor.
- LLM'li denetim, yalnız arama puanına göre daha isabetli (precision 0.950'ye karşı 0.746). Ayrıca doğrulanmış alıntı veriyor.
- Yerel 8B model kullanılabilir düzeyde: hatasız ve ücretsiz, sözleşme başına ~6 dakika sürüyor.
- 14B aynı sözleşmelerde F1'i 0.05 artırıyor ama bu makinede 4 kat yavaş (12 GB kartta reranker CPU'ya alınmak zorunda). Varsayılan 8B kalıyor.

## Ücretli koşu (kullanıcı onayıyla, 8 dolarlık bakiyeye göre küçültüldü)

Gerçekleşen harcama $5.17. Aşağıdaki öneri başlangıçtaki plandı.

### Başlangıç önerisi

Yerel denetimlerin ortalaması: denetim başına ~118 bin girdi ve ~3.8 bin çıktı token'ı. Tokenizer farkı nedeniyle tahminler ±%30 hata payı taşır.

| Koşu | Tahmini maliyet | Önerilen tavan (`--max-cost`) |
|---|---|---|
| `gpt-5.4-mini` her iki iş için, 50 sözleşme | ~$5.3 | $8 |
| `gpt-5.5` değerlendirme + mini, 10 sözleşme | en fazla ~$7.0 (gerçeği daha düşük) | $8 |

Amaç, pahalı modelin farkını ölçerek varsayılan OpenAI modelini seçmek. Kural: mini'nin F1'i ve alıntı doğruluğu gpt-5.5'ten en fazla 0.03 düşükse önerilen model mini olur.
