#!/usr/bin/env python3
"""Generates Mav's PWA icons (brand v3 mark) as PNG, no external dependency.

The mark: a flat emerald disc and an amber dot that cuts a notch into it,
on a midnight tile. Same geometry as icons/favicon.svg.

Usage: python3 make_icons.py
Writes to icons/: 192, 512, 512-maskable, apple-touch (180).
"""

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "icons"
OUT.mkdir(exist_ok=True)

TILE = (14, 17, 22)          # midnight
EMERALD = (52, 211, 157)
AMBER = (245, 176, 79)
SS = 4                       # supersampling per axis (anti-aliasing)

# The mark in a 100x100 box: disc, dot, and the notch the dot cuts.
DISC = (44, 56, 44)
DOT = (82, 18, 16)
NOTCH = 23


def sample(x, y, size, maskable):
    """Colour and alpha at a sub-pixel position."""
    R = size / 2
    dx, dy = x - R, y - R
    if not maskable:
        rr = size * 0.234
        qx = max(abs(dx) - (R - rr), 0)
        qy = max(abs(dy) - (R - rr), 0)
        if math.hypot(qx, qy) > rr:
            return TILE, 0.0
    box = size * (0.56 if maskable else 0.68)
    u = (x - (size - box) / 2) / box * 100
    v = (y - (size - box) / 2) / box * 100
    if math.hypot(u - DOT[0], v - DOT[1]) <= DOT[2]:
        return AMBER, 1.0
    if (math.hypot(u - DISC[0], v - DISC[1]) <= DISC[2]
            and math.hypot(u - DOT[0], v - DOT[1]) > NOTCH):
        return EMERALD, 1.0
    return TILE, 1.0


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
