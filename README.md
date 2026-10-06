# Vakitane — yayın sitesi ve vakit verisi

Bu depo GitHub Pages ile **https://fatihbican96.github.io/vakitane/**
adresinde yayınlanır. Uygulamanın kaynak kodu burada DEĞİL; içinde gizli
bir şey yok.

| Dosya | Ne işe yarar |
|---|---|
| `index.html` | Gizlilik politikası (Play Console bu adresi gösteriyor) |
| `veri-silme.html` | Veri silme talimatları |
| `data/prayer_manifest.json` | Uygulama önce bunu okur (küçük) |
| `data/prayer_bundle.bin` | Tüm ilçelerin vakitleri; yalnızca sürüm değişince indirilir |
| `remote_config.json` | Duyuru ve reklam ayarı |
| `tool/`, `assets/data/` | Veriyi Diyanet'ten çeken araçlar ve ham ilçe paketleri |

## Otomatik güncelleme

`.github/workflows/update-prayer-data.yml` her ayın 1'i ve 15'inde
Diyanet'ten tüm ilçeleri çeker, eldeki verilerle birleştirir, denetler ve
`data/` altına yazar. Başarısız olursa hiçbir şey yayınlanmaz; uygulamalar
eldeki paketle çalışmaya devam eder ve GitHub e-posta ile haber verir.

Elle çalıştırmak: **Actions > Vakit verisini yenile > Run workflow**.

## Bilmen gerekenler

- Üst üste hata geliyorsa Diyanet sayfasının yapısı değişmiş olabilir;
  `tool/fetch_diyanet.py` güncellenmeli.
- GitHub 60 gün değişiklik olmayan depoda zamanlanmış işi durdurur. İş
  her çalıştığında depoya yazdığı için normalde olmaz; durursa Actions
  sekmesinde "Enable workflow" de.
- **Duyuru:** `remote_config.json` içinde `announcement.enabled: true`,
  metin ve bitiş tarihi (`until`) yaz. Tarih geçince kendiliğinden kaybolur.
- Bu dosyalardaki araçların asıl kopyası uygulama projesinde
  (`Vakitane/tool/`). Orada değiştirirsen buraya da kopyala.
