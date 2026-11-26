"""Данные для карты в карточке вызова: точка, настройки и ссылки во внешние карты.

Координаты берутся из API (поля lat/lon, см. _norm_call в api_client.py).
Адрес вызова на внешние сервисы автоматически НЕ отправляется: ссылки на
Яндекс.Карты и 2ГИС открываются только по нажатию сотрудника.
"""
from urllib.parse import quote

import config


def build(call):
    lat, lon = call.get("lat"), call.get("lon")
    has_point = lat is not None and lon is not None
    address = (call.get("address") or "").strip()

    links = []
    if has_point:
        links.append(("Маршрут в Яндекс.Картах", "https://yandex.ru/maps/?rtext=~%.6f,%.6f&rtt=auto" % (lat, lon)))
        links.append(("Яндекс.Карты", "https://yandex.ru/maps/?pt=%.6f,%.6f&z=17&l=map" % (lon, lat)))
        links.append(("2ГИС", "https://2gis.ru/?m=%.6f,%.6f/17" % (lon, lat)))
    elif address:
        query = quote(address, safe="")
        links.append(("Яндекс.Карты", "https://yandex.ru/maps/?text=" + query))
        links.append(("2ГИС", "https://2gis.ru/search/" + query))

    return {
        "show": bool(links),
        "embedded": bool(config.MAP_ENABLED and has_point),
        "has_point": has_point,
        "lat": lat,
        "lon": lon,
        "zoom": config.MAP_ZOOM,
        "tiles": config.MAP_TILE_URL,
        "attribution": config.MAP_ATTRIBUTION,
        "links": links,
    }
