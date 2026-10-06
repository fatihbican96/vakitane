#!/usr/bin/env python3
"""Tek tek ilce paketlerini TEK bir ikili dosyada birlestirir.

Neden: 869 ilcenin ham JSON'u ~25 MB. Uygulamaya gomulemeyecek kadar buyuk,
ama kullanici "internetsiz de tum sehirler calissin" istiyor. Veride uc
buyuk tekrar var ve ucu de burada temizleniyor:

  1. Tarih anahtarlari ("2026-09-01") her ilcede tekrar ediyor
     -> tarih listesi BIR KEZ, ortak saklaniyor.

  2. Hicri tarih ("19 Rebiulevvel 1448") her ilcede tekrar ediyor.
     Olcum: 396 gun x 30 ilce, SIFIR farklilik -- hicri tarih konuma degil
     yalnizca takvime bagli.
     -> hicri tablosu da BIR KEZ, ortak.

  3. Ardisik gunlerin vakitleri 1-2 dakika farkla degisiyor.
     Olcum: farklarin %100'u tek isaretli bayta siğiyor (-65..+91; uctaki
     degerler yaz saati gecisleri).
     -> gunluk mutlak deger yerine ONCEKI GUNDEN FARK saklaniyor.

Sonuc: ~25 MB -> ~2 MB.

Kullanim:
    python tool/build_pack_bundle.py
"""

from __future__ import annotations

import datetime
import glob
import gzip
import io
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets", "data")
PACKS = os.path.join(ASSETS, "prayer_packs")
OUT = os.path.join(ASSETS, "prayer_bundle.bin")

MAGIC = b"VKTB"
VERSION = 1
EPOCH = datetime.date(1970, 1, 1)

# Fark tek bayta sigmazsa bu kacis degeri yazilir ve ardindan mutlak
# deger int16 olarak gelir. Olcumde hic gerekmedi ama kaynak degisirse
# sessizce bozulmaktansa buyuyerek dogru kalsin.
ESCAPE = -128


def epoch_day(iso: str) -> int:
    return (datetime.date.fromisoformat(iso) - EPOCH).days


def build() -> None:
    files = sorted(glob.glob(os.path.join(PACKS, "*.json")))
    if not files:
        sys.exit("paket yok -- once `python tool/fetch_diyanet.py packs` calistirin")

    packs = []
    all_dates: set[str] = set()
    hijri_of: dict[str, str] = {}
    for f in files:
        p = json.load(io.open(f, encoding="utf-8"))
        packs.append(p)
        all_dates.update(p["days"])
        # Hicri tum ilcelerde ayni; ilk gorenin degeri yeterli.
        for d, h in p["hijri"].items():
            hijri_of.setdefault(d, h)

    dates = sorted(all_dates)
    day_index = {d: i for i, d in enumerate(dates)}
    n_days = len(dates)
    print(f"ilce: {len(packs)}, gun: {n_days} ({dates[0]} .. {dates[-1]})")

    # --- ortak hicri tablosu -------------------------------------------------
    uniq_hijri: list[str] = []
    hijri_id: dict[str, int] = {}
    for d in dates:
        h = hijri_of.get(d, "")
        if h not in hijri_id:
            hijri_id[h] = len(uniq_hijri)
            uniq_hijri.append(h)
    print(f"benzersiz hicri metni: {len(uniq_hijri)} (tekrar orani "
          f"{100 * (1 - len(uniq_hijri) / max(n_days, 1)):.0f}%)")

    # --- ilce bloklari -------------------------------------------------------
    bitmap_bytes = (n_days + 7) // 8
    blocks: list[tuple[int, bytes]] = []
    escapes = 0

    for p in packs:
        bm = bytearray(bitmap_bytes)
        body = bytearray()
        prev: list[int] | None = None

        for d in dates:
            t = p["days"].get(d)
            if t is None:
                continue
            i = day_index[d]
            bm[i >> 3] |= 1 << (i & 7)
            if prev is None:
                for v in t:
                    body += struct.pack("<H", v)
            else:
                for a, b in zip(prev, t):
                    delta = b - a
                    if -127 <= delta <= 127:
                        body += struct.pack("<b", delta)
                    else:
                        body += struct.pack("<b", ESCAPE)
                        body += struct.pack("<H", b)
                        escapes += 1
            prev = t

        blocks.append((p["id"], bytes(bm) + bytes(body)))

    if escapes:
        print(f"kacis kullanildi: {escapes} kez")

    # --- dosyayi yaz ---------------------------------------------------------
    head = bytearray()
    head += MAGIC
    head += struct.pack("<B", VERSION)
    head += struct.pack("<I", n_days)
    for d in dates:
        head += struct.pack("<i", epoch_day(d))
    head += struct.pack("<H", len(uniq_hijri))
    for h in uniq_hijri:
        raw = h.encode("utf-8")
        head += struct.pack("<B", len(raw)) + raw
    for d in dates:
        head += struct.pack("<H", hijri_id[hijri_of.get(d, "")])
    head += struct.pack("<H", len(blocks))

    # Indeks: her ilce icin (id, offset, uzunluk). Offset, bloklarin
    # basladigi yere gore. Boylece Dart tarafi tum dosyayi cozmeden
    # istedigi ilcenin dilimini okuyabilir.
    index = bytearray()
    offset = 0
    for did, blk in blocks:
        index += struct.pack("<IiI", did, offset, len(blk))
        offset += len(blk)

    body_all = b"".join(blk for _, blk in blocks)
    data = bytes(head) + bytes(index) + body_all

    with io.open(OUT, "wb") as f:
        f.write(data)

    raw_total = sum(os.path.getsize(f) for f in files)
    gz = len(gzip.compress(data, 9))
    print(f"\nham JSON toplami : {raw_total:>12,} bayt  ({raw_total/1e6:.1f} MB)")
    print(f"ikili paket      : {len(data):>12,} bayt  ({len(data)/1e6:.2f} MB)")
    print(f"  basliklar      : {len(head):>12,} bayt")
    print(f"  indeks         : {len(index):>12,} bayt")
    print(f"  ilce verisi    : {len(body_all):>12,} bayt "
          f"({len(body_all)//max(len(blocks),1):,}/ilce)")
    print(f"gzip'lenmis hali : {gz:>12,} bayt  ({gz/1e6:.2f} MB)")
    print(f"\nkazanc: {raw_total/len(data):.1f}x kucuk -> {OUT}")


if __name__ == "__main__":
    build()
