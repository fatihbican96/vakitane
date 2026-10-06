#!/usr/bin/env python3
"""Diyanet namaz vakti verisini indirip uygulama varliklarina donusturur.

Bu script UYGULAMANIN PARCASI DEGILDIR. Gelistirme makinesinde yilda bir
kez calistirilir; ciktisi assets/ altina yazilir ve uygulamayla birlikte
dagitilir. Kullanicinin telefonu Diyanet'e hicbir istek atmaz.

Neden boyle:
  Diyanet'in resmi API'si (awqatsalah.diyanet.gov.tr) endpoint basina 5,
  yillik veri icin ayda 10 istekle sinirli. Milyonlarca cihazin cagirmasi
  mumkun degil. Buna karsilik halka acik vakit sayfasi tek istekte epeyce
  gun donduruyor.

NE SIKLIKLA CALISTIRILMALI: AYDA BIR.
  Sayfa uc tablo iceriyor ve ucu de SABIT aralikli, ay/yil parametresi YOK:
    haftalik : bugunden 7 gun
    aylik    : bugunden 31 gun
    yillik   : GELECEK takvim yili (ornegin Agustos 2026'da tum 2027)
  Yani "icinde bulunulan yilin kalani" hicbir zaman sayfada yok. Agustos
  2026'da cekilen veri Agu30-Eyl29 + tum 2027'yi verir; Eki-Ara 2026 bos
  kalir. Bu bir hata degil, sayfanin yapisi.

  Cozum: paketler UZERINE YAZILMAZ, BIRLESTIRILIR. Ayda bir calistirildiginda
  her calisma sonraki 31 gunu ekler, boylece bosluk hic olusmaz. Kalan
  bosluklar (bugunden 31 gun sonrasi ile yil sonu arasi) uygulamada
  Katman 3 ile hesaplanir ve o gunler yaklastikca gercek veriyle degisir.

Kullanim:
    python tool/fetch_diyanet.py districts      # il/ilce listesi
    python tool/fetch_diyanet.py times 9541     # tek ilce (deneme)
    python tool/fetch_diyanet.py packs          # ilk kurulum: eksik ilceler
    python tool/fetch_diyanet.py refresh        # aylik: TUM ilceleri yenile
"""

from __future__ import annotations

import gzip
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

BASE = "https://namazvakitleri.diyanet.gov.tr"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

# Sunucuya nazik davran: istekler arasi bekleme (saniye).
# Yilda bir calisan bir script icin acele etmeye gerek yok.
DELAY = 1.0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "data")
PACKS = os.path.join(ASSETS, "prayer_packs")

TURKISH_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}


def get(url: str, *, tries: int = 3) -> str:
    """Sayfayi indirir. gzip'i acar, gecici hatalarda tekrar dener."""
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept-Encoding": "gzip",
                    "Accept-Language": "tr-TR,tr;q=0.9",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"indirilemedi: {url} ({last})")


# ---------------------------------------------------------------------------
# 1) Il / ilce listesi
# ---------------------------------------------------------------------------

def fetch_districts() -> list[dict[str, Any]]:
    """Diyanet'in kendi il/ilce listesini cikarir.

    Onemli: bu liste 973 idari ilceden KUCUKTUR. Diyanet yalnizca vakti
    anlamli olcude farklilasan yerleri ayri kaydediyor. Uygulamanin sehir
    listesi de bu olmali -- kullaniciya Diyanet'te karsiligi olmayan bir
    yer gostermek, sonra o yer icin vakit uretememek demek.
    """
    url = f"{BASE}/tr-TR/home/GetRegList?ChangeType=country&CountryId=2&Culture=tr-TR"
    provinces = json.loads(get(url))["StateList"]
    print(f"il sayisi: {len(provinces)}")

    out: list[dict[str, Any]] = []
    for i, p in enumerate(provinces, 1):
        sid, sname = p["SehirID"], p["SehirAdi"].strip()
        durl = (
            f"{BASE}/tr-TR/home/GetRegList"
            f"?ChangeType=state&CountryId=2&StateId={sid}&Culture=tr-TR"
        )
        regions = json.loads(get(durl)).get("StateRegionList") or []
        for d in regions:
            out.append({
                "id": int(d["IlceID"]),
                "district": d["IlceAdi"].strip(),
                "province": sname,
                "provinceId": int(sid),
            })
        print(f"  [{i:>2}/{len(provinces)}] {sname}: {len(regions)} ilce")
        time.sleep(DELAY)

    out.sort(key=lambda x: (x["province"], x["district"]))
    return out


# ---------------------------------------------------------------------------
# 2) Vakitler
# ---------------------------------------------------------------------------

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"^(\d{1,2})\s+(\S+)\s+(\d{4})")


def _clean(cell: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", cell))).strip()


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def fetch_times(district_id: int) -> dict[str, Any]:
    """Bir ilcenin tam yillik vakitlerini tek istekte cikarir.

    Cikti formati (Dart tarafi bunu okur -- degistirirsen
    lib/data/prayer/prayer_pack.dart dosyasini da guncelle):

        {
          "id": 9541,
          "days": {
            "2026-09-01": [293, 383, 789, 1009, 1185, 1269],
            ...
          },
          "hijri": {"2026-09-01": "19 Rebiulevvel 1448", ...}
        }

    Vakitler gece yarisindan itibaren DAKIKA cinsinden ve her zaman
    [imsak, gunes, ogle, ikindi, aksam, yatsi] sirasinda. Tam gun sayisi
    kaynaga gore degisir (genelde ~400 gun; icinde bulunulan yilin kalani
    + sonraki yilin bir kismi).
    """
    url = f"{BASE}/tr-TR/{district_id}/x-icin-namaz-vakti"
    page = get(url)

    days: dict[str, list[int]] = {}
    hijri: dict[str, str] = {}

    for row in _ROW_RE.findall(page):
        cells = [_clean(c) for c in _CELL_RE.findall(row)]
        cells = [c for c in cells if c]
        if len(cells) < 8:
            continue
        m = _DATE_RE.match(cells[0])
        if not m:
            continue
        day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = TURKISH_MONTHS.get(month_name)
        if not month:
            continue
        times = cells[2:8]
        if not all(re.fullmatch(r"\d{1,2}:\d{2}", t) for t in times):
            continue
        key = f"{year:04d}-{month:02d}-{day:02d}"
        days[key] = [_to_minutes(t) for t in times]
        hijri[key] = cells[1]

    if not days:
        raise RuntimeError(f"ilce {district_id}: vakit satiri bulunamadi")

    return {"id": district_id, "days": days, "hijri": hijri}


def save_merged(
    pack: dict[str, Any], path: str, *, keep_from: str | None = None
) -> tuple[int, int]:
    """Paketi diske yazar; dosya varsa UZERINE YAZMAZ, birlestirir.

    Sayfa her seferinde farkli bir pencere donduruyor (bkz. modul dokumani).
    Uzerine yazmak onceki aylarda toplanmis gunleri silerdi.

    Doner: (eklenen gun, toplam gun)
    """
    merged: dict[str, list[int]] = {}
    hijri: dict[str, str] = {}
    if os.path.exists(path):
        old = json.load(io.open(path, encoding="utf-8"))
        merged.update(old.get("days", {}))
        hijri.update(old.get("hijri", {}))

    before = len(merged)
    # Yeni veri onceligi alir: Diyanet bir gunu guncellerse duzeltme gelsin.
    merged.update(pack["days"])
    hijri.update(pack.get("hijri", {}))

    # Gecmis gunler budanir: paket her ay buyumesin. [keep_from] "YYYY-AA-GG".
    if keep_from:
        merged = {k: v for k, v in merged.items() if k >= keep_from}
        hijri = {k: v for k, v in hijri.items() if k >= keep_from}

    out = {
        "id": pack["id"],
        "days": dict(sorted(merged.items())),
        "hijri": dict(sorted(hijri.items())),
    }
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return len(merged) - before, len(merged)


# ---------------------------------------------------------------------------
# Komutlar
# ---------------------------------------------------------------------------

def cmd_districts() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    data = fetch_districts()
    path = os.path.join(ASSETS, "tr_districts.json")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n{len(data)} ilce yazildi -> {path} ({os.path.getsize(path):,} bayt)")


def cmd_times(district_id: int, *, save: bool = False) -> None:
    pack = fetch_times(district_id)
    if save:
        os.makedirs(PACKS, exist_ok=True)
        added, kept = save_merged(pack, os.path.join(PACKS, f"{district_id}.json"))
        print(f"kaydedildi: +{added} yeni gun, toplam {kept} gun")
    keys = sorted(pack["days"])
    print(f"ilce {district_id}: {len(keys)} gun ({keys[0]} .. {keys[-1]})")
    for k in keys[:3]:
        t = pack["days"][k]
        pretty = " ".join(f"{v // 60:02d}:{v % 60:02d}" for v in t)
        print(f"  {k}  {pretty}   [{pack['hijri'][k]}]")


def cmd_packs() -> None:
    path = os.path.join(ASSETS, "tr_districts.json")
    if not os.path.exists(path):
        sys.exit("once `python tool/fetch_diyanet.py districts` calistirin")
    districts = json.load(io.open(path, encoding="utf-8"))
    os.makedirs(PACKS, exist_ok=True)

    total, failed = len(districts), []
    for i, d in enumerate(districts, 1):
        out = os.path.join(PACKS, f"{d['id']}.json")
        if os.path.exists(out):
            continue
        try:
            pack = fetch_times(d["id"])
            with io.open(out, "w", encoding="utf-8", newline="\n") as f:
                json.dump(pack, f, ensure_ascii=False, separators=(",", ":"))
            print(f"[{i:>4}/{total}] {d['province']}/{d['district']}: "
                  f"{len(pack['days'])} gun")
        except Exception as e:  # noqa: BLE001 - tek ilce patlarsa devam et
            failed.append((d["id"], str(e)))
            print(f"[{i:>4}/{total}] {d['province']}/{d['district']}: HATA {e}")
        time.sleep(DELAY)

    print(f"\nbitti. basarisiz: {len(failed)}")
    for fid, err in failed:
        print(f"  {fid}: {err}")


def cmd_refresh() -> None:
    """TUM ilceleri yeniden ceker ve mevcut paketlerle BIRLESTIRIR.

    `packs` komutu dosyasi olan ilceyi ATLIYOR (ilk kurulum icin); aylik
    yenilemede o yuzden hicbir ilce tazelenmiyordu. Bu komut her ilceyi
    ceker, yeni gunleri ekler, 30 gunden eski gunleri budar.

    GitHub Actions ayda iki kez bunu calistirir (bkz. veri deposundaki
    .github/workflows/update-prayer-data.yml). Ilcelerin %10'undan
    fazlasi basarisiz olursa 1 ile cikar: is kirmizi olur, eski paket
    yayinda kalir, uygulama etkilenmez.
    """
    import datetime as _dt

    path = os.path.join(ASSETS, "tr_districts.json")
    districts = json.load(io.open(path, encoding="utf-8"))
    os.makedirs(PACKS, exist_ok=True)
    keep_from = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()

    total, failed = len(districts), []
    for i, d in enumerate(districts, 1):
        out = os.path.join(PACKS, f"{d['id']}.json")
        try:
            pack = fetch_times(d["id"])
            added, kept = save_merged(pack, out, keep_from=keep_from)
            print(f"[{i:>4}/{total}] {d['province']}/{d['district']}: "
                  f"+{added} gun, toplam {kept}")
        except Exception as e:  # noqa: BLE001 - tek ilce patlarsa devam et
            failed.append((d["id"], str(e)))
            print(f"[{i:>4}/{total}] {d['province']}/{d['district']}: HATA {e}")
        time.sleep(DELAY)

    print(f"\nbitti. basarisiz: {len(failed)} / {total}")
    for fid, err in failed[:20]:
        print(f"  {fid}: {err}")
    if len(failed) > total * 0.10:
        sys.exit("cok fazla ilce basarisiz -- paket YAYINLANMAMALI")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd = args[0]
    if cmd == "districts":
        cmd_districts()
    elif cmd == "times":
        cmd_times(int(args[1]), save="--save" in args)
    elif cmd == "packs":
        cmd_packs()
    elif cmd == "refresh":
        cmd_refresh()
    else:
        sys.exit(f"bilinmeyen komut: {cmd}")
