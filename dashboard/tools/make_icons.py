#!/usr/bin/env python3
"""Generates Mav's PWA icons (brand v2 mark) as PNG, no external dependency.

The mark: an emerald disc crossed by an amber arc, on a midnight tile.

Usage: python3 make_icons.py
Produit dans icons/ : 192, 512, 512-maskable, apple-touch (180).
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "icons"
OUT.mkdir(exist_ok=True)

# Palette (brand v2 — "Midnight & Emerald")
TILE_TOP = (20, 24, 29)      # midnight
TILE_BOT = (11, 13, 16)
EM_LIGHT = (52, 211, 157)    # emerald, lit side
EM_DARK = (10, 74, 56)       # emerald, shade
AMBER = (245, 176, 79)       # signal
WHITE = (255, 255, 255)
SS = 3                       # supersampling per axis (anti-aliasing)


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def sample(x, y, size, maskable):
    """Colour and alpha at a sub-pixel position."""
    cx = cy = size / 2
    dx, dy = x - cx, y - cy
    R = size / 2
    if not maskable:
        rr = size * 0.22
        qx = max(abs(dx) - (R - rr), 0)
        qy = max(abs(dy) - (R - rr), 0)
        if math.hypot(qx, qy) > rr:
            return (0, 0, 0), 0.0
    col = lerp(TILE_TOP, TILE_BOT, y / size)
    orb_r = size * (0.33 if maskable else 0.36)
    r = math.hypot(dx, dy)
    if r <= orb_r:
        # Lit from the top-left, shaded bottom-right.
        t = math.hypot(x - size * 0.38, y - size * 0.34) / (orb_r * 1.7)
        col = lerp(EM_LIGHT, EM_DARK, t)
        glint = max(0.0, 1.0 - math.hypot(x - size * 0.40, y - size * 0.36) / (orb_r * 0.55))
        col = lerp(col, WHITE, glint * 0.45)
        # The amber orbit: a thin arc whose tail fades, led by a small sun.
        ring_r, ring_w = orb_r * 0.62, orb_r * 0.055
        ang = math.degrees(math.atan2(dy, dx))  # 0 = right, -90 = up
        head = 10.0
        if abs(r - ring_r) <= ring_w and -190 <= ang <= head or (ang > 160 and abs(r - ring_r) <= ring_w):
            a = ang - 360 if ang > 160 else ang
            tail = max(0.0, min(1.0, (a + 190) / 120))
            col = lerp(col, AMBER, tail ** 1.4)
        hx = cx + ring_r * math.cos(math.radians(head))
        hy = cy + ring_r * math.sin(math.radians(head))
        dh = math.hypot(x - hx, y - hy)
        if dh <= ring_w * 2.1:
            col = lerp(AMBER, (255, 236, 200), max(0.0, 1 - dh / (ring_w * 1.2)) * 0.6)
        elif dh <= ring_w * 4:
            col = lerp(col, AMBER, (1 - (dh - ring_w * 2.1) / (ring_w * 1.9)) * 0.35)
    elif r <= orb_r * 1.12:
        # Soft emerald glow around the disc.
        col = lerp(lerp(col, EM_LIGHT, 0.25), col, (r - orb_r) / (orb_r * 0.12))
    return col, 1.0


def pixel(x, y, size, maskable=False):
    acc = [0.0, 0.0, 0.0]
    alpha = 0.0
    for i in range(SS):
        for j in range(SS):
            c, a = sample(x + (i + 0.5) / SS, y + (j + 0.5) / SS, size, maskable)
            for k in range(3):
                acc[k] += c[k] * a
            alpha += a
    n = SS * SS
    if alpha == 0:
        return (0, 0, 0, 0)
    return tuple(round(acc[k] / alpha) for k in range(3)) + (round(255 * alpha / n),)


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
