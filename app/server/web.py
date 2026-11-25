"""The page itself: index, assets, service worker, manifest, icons."""
import os
import struct
import zlib

from aiohttp import web

from .common import HERE

# ---------- static / PWA ----------

def png_icon(n):
    """A plain app icon (accent square + white play triangle), drawn without image libraries."""
    bg, fg = (0xD9, 0x3A, 0x5B), (255, 255, 255)
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            u, v = x / n, y / n
            inside = 0.38 <= u <= 0.74 and abs(v - 0.5) <= 0.22 * (0.74 - u) / 0.36   # play triangle
            row += bytes(fg if inside else bg)
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


ICONS = {}


async def icon(req):
    n = int(req.match_info["n"])
    if n not in (192, 512):
        raise web.HTTPNotFound()
    if n not in ICONS:
        ICONS[n] = png_icon(n)
    return web.Response(body=ICONS[n], content_type="image/png", headers={"Cache-Control": "max-age=604800"})


MANIFEST = {"name": "Kassetto", "short_name": "Kassetto", "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#0c0c10", "theme_color": "#0c0c10",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}


async def manifest(req):
    return web.json_response(MANIFEST, content_type="application/manifest+json")


async def sw(req):
    return web.FileResponse(os.path.join(HERE, "static", "sw.js"),
                            headers={"Content-Type": "application/javascript", "Cache-Control": "no-cache"})


async def asset(req):
    """Vite's hashed build output: immutable, cache forever."""
    name = req.match_info["name"]
    path = os.path.join(HERE, "static", "assets", name)
    if "/" in name or name.startswith(".") or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})


async def index(req):
    return web.FileResponse(os.path.join(HERE, "static", "index.html"), headers={"Cache-Control": "no-cache"})
