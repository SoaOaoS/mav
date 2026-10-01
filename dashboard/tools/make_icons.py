#!/usr/bin/env python3
"""Génère les icônes PWA de Mav (orbe sauge) en PNG, sans dépendance externe.

Usage: python3 make_icons.py
Produit dans icons/ : 192, 512, 512-maskable, apple-touch (180).
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "icons"
OUT.mkdir(exist_ok=True)

# Palette
BG_TOP = (47, 111, 94)      # vert profond
BG_BOT = (124, 196, 172)    # sauge clair
GLOW = (143, 211, 190)
WHITE = (255, 255, 255)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def pixel(x, y, size, maskable=False):
    cx = cy = (size - 1) / 2
    dx, dy = x - cx, y - cy
    r = (dx * dx + dy * dy) ** 0.5
    R = size * 0.5

    # Fond dégradé vertical
    bg = lerp(BG_TOP, BG_BOT, y / (size - 1))

    # Marge de sécurité pour l'icône maskable (contenu dans 80%)
    inner = 0.40 if maskable else 0.46
    orb_r = size * inner
    edge = orb_r * 0.12

    # Extérieur : fond (coins transparents si non maskable pour un bel arrondi)
    if not maskable:
        rr = size * 0.22
        # rectangle arrondi
        qx = max(abs(dx) - (R - rr), 0)
        qy = max(abs(dy) - (R - rr), 0)
        if (qx * qx + qy * qy) ** 0.5 > rr:
            return (0, 0, 0, 0)

    if r > orb_r + edge:
        return (*bg, 255)

    # Halo autour de l'orbe
    if r > orb_r:
        t = (r - orb_r) / edge
        col = lerp(GLOW, bg, t)
        return (*col, 255)

    # Dégradé radial de l'orbe
    t = min(r / orb_r, 1.0)
    base = lerp((124, 196, 172), (47, 111, 94), t)

    # Reflet en haut-gauche
    glint_d = ((x - size * 0.36) ** 2 + (y - size * 0.33) ** 2) ** 0.5
    g = max(0.0, 1.0 - glint_d / (orb_r * 0.9))
    base = lerp(base, WHITE, min(1.0, g * 1.4))

    # Ombre douce en bas
    shade_d = ((x - size * 0.66) ** 2 + (y - size * 0.78) ** 2) ** 0.5
    s = max(0.0, 1.0 - shade_d / (orb_r * 1.2))
    base = lerp(base, (20, 60, 50), s * 0.35)

    return (*base, 255)


def write_png(path, size, maskable=False):
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filtre None
        for x in range(size):
            raw.extend(pixel(x, y, size, maskable))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        c += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        return c

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)
    print(f"{path} ({size}x{size}, {len(png)} o)")


def main():
    write_png(OUT / "icon-192.png", 192)
    write_png(OUT / "icon-512.png", 512)
    write_png(OUT / "icon-512-maskable.png", 512, maskable=True)
    write_png(OUT / "apple-touch-icon.png", 180, maskable=True)


if __name__ == "__main__":
    main()
