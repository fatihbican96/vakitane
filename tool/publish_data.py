#!/usr/bin/env python3
"""Vakit paketini uygulamanın indireceği yere hazırlar.

    python tool/publish_data.py docs/data

Hedef klasöre iki dosya yazar:

  prayer_bundle.bin       build_pack_bundle.py çıktısının kopyası
  prayer_manifest.json    uygulamanın ÖNCE okuduğu küçük dosya:
      {"format": 1, "version": "...", "size": ..., "sha256": "...",
       "firstDay": "2026-09-06", "lastDay": "2027-12-31", "districts": 869}

Uygulama (lib/data/prayer/prayer_data_updater.dart) yalnızca manifest'teki
"version" değiştiğinde paketi indirir, boyutu ve sha256'yı doğrular.

YAYINLAMADAN ÖNCE DENETLER: bozuk ya da eksik bir paketin milyonlarca
cihaza gitmesi, hiç güncelleme olmamasından kötüdür. Denetim tutmazsa
1 ile çıkar ve hiçbir şey yazmaz.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "assets", "data", "prayer_bundle.bin")

# prayer_bundle.dart ile aynı. Biçim değişirse "format" artırılır;
# eski uygulamalar tanımadıkları biçimi indirmez.
MAGIC = b"VKTB"
VERSION = 1
FORMAT = 1

MIN_DISTRICTS = 800
# Paket bugünden en az bu kadar gün ilerisini kapsamalı.
MIN_DAYS_AHEAD = 25


def inspect(data: bytes) -> dict:
    if data[:4] != MAGIC:
        sys.exit("paket imzasi tanınmadı")
    if data[4] != VERSION:
        sys.exit(f"paket sürümü {data[4]}, beklenen {VERSION}")
    p = 5
    (n,) = struct.unpack_from("<I", data, p)
    p += 4
    days = struct.unpack_from(f"<{n}i", data, p)
    p += 4 * n
    (hc,) = struct.unpack_from("<H", data, p)
    p += 2
    for _ in range(hc):
        p += 1 + data[p]
    p += 2 * n
    (districts,) = struct.unpack_from("<H", data, p)

    epoch = datetime.date(1970, 1, 1)
    first = epoch + datetime.timedelta(days=days[0])
    last = epoch + datetime.timedelta(days=days[-1])
    return {"first": first, "last": last, "districts": districts, "days": n}


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out_dir = sys.argv[1]

    data = open(BUNDLE, "rb").read()
    info = inspect(data)

    today = datetime.date.today()
    if info["districts"] < MIN_DISTRICTS:
        sys.exit(f"yalnızca {info['districts']} ilçe var (en az {MIN_DISTRICTS})")
    if info["last"] < today + datetime.timedelta(days=MIN_DAYS_AHEAD):
        sys.exit(f"paket {info['last']} tarihinde bitiyor; çok kısa")
    if not (info["first"] <= today):
        sys.exit(f"paket bugünü kapsamıyor (ilk gün {info['first']})")

    manifest = {
        "format": FORMAT,
        "version": datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "firstDay": info["first"].isoformat(),
        "lastDay": info["last"].isoformat(),
        "districts": info["districts"],
    }

    os.makedirs(out_dir, exist_ok=True)
    shutil.copyfile(BUNDLE, os.path.join(out_dir, "prayer_bundle.bin"))
    # Manifest EN SON yazılır: uygulama yeni manifest'i görüp eski paketi
    # indirmesin.
    with open(os.path.join(out_dir, "prayer_manifest.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
