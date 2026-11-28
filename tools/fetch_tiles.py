#!/usr/bin/env python3
"""Предзагрузка тайлов 2ГИС в локальный диск-кэш data/tiles.

Запуск из корня проекта:
    python tools/fetch_tiles.py

Диапазон зумов и область можно переопределить аргументами:
    python tools/fetch_tiles.py --bbox 43.40,39.30,43.95,40.00 --zooms 11-14
"""
import argparse
import math
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402


def latlon_to_tile(lat, lon, z):
    n = 1 << z
    lon = max(-180.0, min(180.0, float(lon)))
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0 * n
    )
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def parse_bbox(raw):
    values = tuple(float(v) for v in raw.split(","))
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("bbox должен быть min_lat,min_lon,max_lat,max_lon")
    return values


def parse_zooms(raw):
    if "-" in raw:
        zmin, zmax = (int(part) for part in raw.split("-", 1))
    else:
        zmin = zmax = int(raw)
    zmin, zmax = max(0, min(18, zmin)), max(0, min(18, zmax))
    if zmin > zmax:
        raise ValueError("неверный диапазон зумов")
    return zmin, zmax


def tile_path(z, x, y):
    return os.path.join(config.MAP_TILE_CACHE_DIR, str(z), str(x), "%d.png" % y)


def fetch_tile(z, x, y, overwrite=False):
    path = tile_path(z, x, y)
    if os.path.isfile(path) and not overwrite:
        return "cached"

    if not all(k in config.MAP_TILE_UPSTREAM for k in ("{x}", "{y}", "{z}")):
        raise RuntimeError("MAP_TILE_UPSTREAM должен содержать {x}, {y}, {z}")
    url = config.MAP_TILE_UPSTREAM.format(x=x, y=y, z=z)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://2gis.ru/",
        "Accept": "image/png,image/*;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=config.API_TIMEOUT)
    if resp.status_code != 200 or not resp.content:
        raise RuntimeError("HTTP %s" % resp.status_code)
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype not in ("image/png", "image/jpeg", "image/webp"):
        raise RuntimeError("Content-Type: %s" % ctype)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="tile-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(resp.content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return "downloaded"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bbox", default=config.MAP_PRECACHE_BBOX)
    parser.add_argument("--zooms", default=config.MAP_PRECACHE_ZOOMS)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    min_lat, min_lon, max_lat, max_lon = parse_bbox(args.bbox)
    zmin, zmax = parse_zooms(args.zooms)

    jobs = []
    for z in range(zmin, zmax + 1):
        x1, y1 = latlon_to_tile(max_lat, min_lon, z)
        x2, y2 = latlon_to_tile(min_lat, max_lon, z)
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                jobs.append((z, x, y))

    print("Тайлов: %d, зумы: %d-%d, кэш: %s" % (
        len(jobs), zmin, zmax, config.MAP_TILE_CACHE_DIR
    ))

    stats = {"cached": 0, "downloaded": 0, "failed": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_tile, z, x, y, args.overwrite): (z, x, y)
            for z, x, y in jobs
        }
        for future in as_completed(futures):
            z, x, y = futures[future]
            try:
                stats[future.result()] += 1
            except Exception as exc:
                stats["failed"] += 1
                print("Не скачан %d/%d/%d: %s" % (z, x, y, exc))

    print("Готово: скачано %(downloaded)d, уже было %(cached)d, ошибок %(failed)d" % stats)


if __name__ == "__main__":
    main()
