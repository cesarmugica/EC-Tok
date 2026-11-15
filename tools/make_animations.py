"""Genera el banco inicial de animaciones de EC-Tok (WebP animado con transparencia).

Son dibujos hechos con código para que EC-Tok funcione desde el primer día; cada quien puede
poner las suyas (GIF, WebP, APNG o WebM con transparencia) en %LOCALAPPDATA%\\EC-Tok\\animaciones.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "src" / "web" / "anim"
S = 1024          # se dibuja al doble y se reduce (orillas suaves)
FINAL = 512
FRAMES = 40
MS = 50           # 40 cuadros × 50 ms = 2 s por vuelta
FONT = next((p for p in ["/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if Path(p).is_file()), None)

PINK, CYAN, YELLOW, WHITE, RED = (254, 44, 85, 255), (37, 244, 238, 255), (255, 214, 0, 255), (255, 255, 255, 255), (230, 30, 60, 255)
PALETTE = [PINK, CYAN, YELLOW, (139, 92, 246, 255), (255, 138, 0, 255), WHITE]


def blank() -> Image.Image:
    return Image.new("RGBA", (S, S), (0, 0, 0, 0))


def heart(d: ImageDraw.ImageDraw, cx: float, cy: float, size: float, color) -> None:
    pts = []
    for i in range(60):
        t = i / 60 * 2 * math.pi
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * size / 32, cy - y * size / 32))
    d.polygon(pts, fill=color)


def star4(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color) -> None:
    k = r * .28
    d.polygon([(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k), (cx, cy + r), (cx - k, cy + k),
               (cx - r, cy), (cx - k, cy - k)], fill=color)


def note(d: ImageDraw.ImageDraw, x: float, y: float, s: float, color) -> None:
    d.ellipse([x - s * .55, y - s * .38, x + s * .55, y + s * .38], fill=color)
    d.rectangle([x + s * .38, y - s * 2.2, x + s * .55, y], fill=color)
    d.polygon([(x + s * .55, y - s * 2.2), (x + s * 1.3, y - s * 1.6), (x + s * 1.3, y - s * 1.2), (x + s * .55, y - s * 1.75)], fill=color)


def text_layer(text: str, size: int, fill, stroke, stroke_w: int, shadow=None) -> Image.Image:
    font = ImageFont.truetype(FONT, size) if FONT else ImageFont.load_default()
    box = ImageDraw.Draw(blank()).textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    w, h = box[2] - box[0] + 40, box[3] - box[1] + 40
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shadow:
        d.text((20 - box[0] + 10, 20 - box[1] + 10), text, font=font, fill=shadow, stroke_width=stroke_w, stroke_fill=shadow)
    d.text((20 - box[0], 20 - box[1]), text, font=font, fill=fill, stroke_width=stroke_w, stroke_fill=stroke)
    return img


def paste_center(base: Image.Image, layer: Image.Image, cx: float, cy: float, scale: float = 1.0, angle: float = 0.0) -> None:
    if scale != 1.0:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.LANCZOS)
    if angle:
        layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    base.alpha_composite(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)))


# ---------------------------------------------------------------------------
def corazones(t: float, rnd=random.Random(1)) -> Image.Image:
    img = blank()
    d = ImageDraw.Draw(img)
    if not hasattr(corazones, "items"):
        corazones.items = [(rnd.uniform(.1, .9), rnd.choice([1, 1, 2]), rnd.random(), rnd.uniform(60, 130),
                            rnd.choice([PINK, RED, (255, 105, 180, 255), (255, 160, 200, 255)])) for _ in range(18)]
    for x0, speed, ph, size, color in corazones.items:
        p = (t * speed + ph) % 1
        y = S * (1.1 - p * 1.25)
        x = S * x0 + math.sin((p + ph) * 2 * math.pi * 1.5) * 50
        shrink = 1 if p < .75 else max(0.05, 1 - (p - .75) / .25)
        heart(d, x, y, size * shrink, color)
    return img


def confeti(t: float) -> Image.Image:
    img = blank()
    d = ImageDraw.Draw(img)
    rnd = random.Random(7)
    for i in range(110):
        ang = rnd.uniform(-math.pi * .95, -math.pi * .05)
        v = rnd.uniform(900, 1700)
        ph = rnd.uniform(0, .25)
        tt = max(0.0, t - ph) * 1.3
        if tt <= 0:
            continue
        x = S / 2 + math.cos(ang) * v * tt
        y = S * .62 + math.sin(ang) * v * tt + 1400 * tt * tt
        if y > S + 40:
            continue
        rot = tt * rnd.uniform(6, 14) + i
        w, h = rnd.uniform(14, 22), rnd.uniform(24, 38)
        c, s_ = math.cos(rot), math.sin(rot)
        pts = [(x + c * dx - s_ * dy, y + s_ * dx + c * dy) for dx, dy in ((-w, -h), (w, -h), (w, h), (-w, h))]
        d.polygon(pts, fill=PALETTE[i % len(PALETTE)])
    return img


def fuegos(t: float) -> Image.Image:
    img = blank()
    d = ImageDraw.Draw(img)
    for k, (cx, cy, color) in enumerate([(.30, .35, PINK), (.70, .30, CYAN), (.50, .55, YELLOW)]):
        life = (t - k / 3) % 1
        if life > .8:
            continue
        p = life / .8
        r = (1 - (1 - p) ** 3) * S * .26
        for j in range(28):
            a = j / 28 * 2 * math.pi
            x, y = S * cx + math.cos(a) * r, S * cy + math.sin(a) * r + p * p * 60
            size = 14 * (1 - p) + 3
            d.line([(S * cx + math.cos(a) * r * .7, S * cy + math.sin(a) * r * .7 + p * p * 40), (x, y)],
                   fill=color[:3] + (int(200 * (1 - p)),), width=int(4 + 4 * (1 - p)))
            d.ellipse([x - size, y - size, x + size, y + size], fill=WHITE if j % 4 == 0 else color)
    return img


def estrellas(t: float) -> Image.Image:
    img = blank()
    d = ImageDraw.Draw(img)
    rnd = random.Random(3)
    for _ in range(14):
        x, y, ph, r = rnd.uniform(.1, .9) * S, rnd.uniform(.1, .9) * S, rnd.random(), rnd.uniform(40, 95)
        k = math.sin(((t + ph) % 1) * math.pi) ** 2
        if k > .03:
            star4(d, x, y, r * k, rnd.choice([YELLOW, WHITE, CYAN, (255, 236, 140, 255)]))
    return img


def thanks(word: str):
    def frame(t: float) -> Image.Image:
        return gracias(t, word)
    return frame


def gracias(t: float, word: str = "¡GRACIAS!") -> Image.Image:
    img = blank()
    key = "layer_" + word
    if not hasattr(gracias, key):
        layer = text_layer(word, 170, WHITE, PINK, 12, shadow=CYAN)
        if layer.width > S * .82:  # que quepa
            layer = layer.resize((int(S * .82), int(layer.height * S * .82 / layer.width)), Image.LANCZOS)
        setattr(gracias, key, layer)
    paste_center(img, getattr(gracias, key), S / 2, S / 2, scale=.88 + .07 * math.sin(t * 2 * math.pi))
    d = ImageDraw.Draw(img)
    for i in range(8):
        a = t * 2 * math.pi + i / 8 * 2 * math.pi
        heart(d, S / 2 + math.cos(a) * S * .40, S / 2 + math.sin(a) * S * .30, 70 + 15 * math.sin(a * 2), PINK if i % 2 else RED)
    return img


def multiplicador(label: str):
    def frame(t: float) -> Image.Image:
        img = blank()
        key = "layer_" + label
        if not hasattr(frame, key):
            setattr(frame, key, text_layer(label, 420, YELLOW, RED, 26, shadow=(120, 0, 30, 255)))
        pulse = 1 + .1 * abs(math.sin(t * 2 * math.pi * 2))
        paste_center(img, getattr(frame, key), S / 2, S / 2, scale=.82 * pulse, angle=-6)
        d = ImageDraw.Draw(img)
        if int(t * 8) % 2 == 0:  # rayos que parpadean
            for cx, cy, flip in ((.14, .30, 1), (.86, .70, -1)):
                x, y = S * cx, S * cy
                d.polygon([(x, y - 120), (x + 50 * flip, y - 10), (x + 10 * flip, y - 10), (x + 40 * flip, y + 120),
                           (x - 40 * flip, y - 30), (x, y - 30)], fill=CYAN)
        star4(d, S * .80, S * .22, 60 * abs(math.sin(t * 2 * math.pi)), WHITE)
        star4(d, S * .22, S * .80, 50 * abs(math.cos(t * 2 * math.pi)), WHITE)
        return img
    return frame


def microfono(t: float) -> Image.Image:
    img = blank()
    mic = Image.new("RGBA", (420, 820), (0, 0, 0, 0))
    d = ImageDraw.Draw(mic)
    d.rounded_rectangle([170, 330, 250, 800], radius=40, fill=(40, 40, 52, 255))
    d.rounded_rectangle([150, 300, 270, 360], radius=20, fill=(190, 190, 205, 255))
    d.ellipse([60, 20, 360, 330], fill=(170, 170, 185, 255))
    cx, cy, rx, ry = 210, 175, 140, 145
    for i in range(-5, 6):  # rejilla (solo dentro del círculo)
        x = cx + i * 26
        if abs(x - cx) < rx:
            dy = ry * math.sqrt(1 - ((x - cx) / rx) ** 2)
            d.line([(x, cy - dy), (x, cy + dy)], fill=(120, 120, 135, 255), width=6)
        y = cy + i * 26
        if abs(y - cy) < ry:
            dx = rx * math.sqrt(1 - ((y - cy) / ry) ** 2)
            d.line([(cx - dx, y), (cx + dx, y)], fill=(120, 120, 135, 255), width=6)
    d.ellipse([60, 20, 360, 330], outline=(225, 225, 235, 255), width=14)
    d.rounded_rectangle([170, 520, 250, 545], radius=10, fill=PINK)
    angle = 12 * math.sin(t * 2 * math.pi)
    paste_center(img, mic, S * .5, S * .58, scale=.95, angle=angle)
    d = ImageDraw.Draw(img)
    for i in range(6):
        p = (t + i / 6) % 1
        x = S * .5 + math.sin(p * 6 + i) * 160 + (i - 2.5) * 40
        y = S * (.42 - p * .38)
        if p < .9:
            note(d, x, y, 42 * (1 - p * .4), PALETTE[i % 4])
    return img


def osito(t: float) -> Image.Image:
    img = blank()
    bear = Image.new("RGBA", (700, 860), (0, 0, 0, 0))
    d = ImageDraw.Draw(bear)
    brown, light, dark = (160, 102, 60, 255), (226, 180, 130, 255), (60, 36, 20, 255)
    a = math.sin(t * 2 * math.pi * 2)
    # piernas (alternando)
    d.rounded_rectangle([230, 640 - 30 * max(0, a), 320, 820 - 30 * max(0, a)], radius=40, fill=brown)
    d.rounded_rectangle([380, 640 - 30 * max(0, -a), 470, 820 - 30 * max(0, -a)], radius=40, fill=brown)
    # brazos (saludando)
    for side, phase in ((-1, 0), (1, math.pi)):
        ang = math.radians(-35 * side + 55 * math.sin(t * 2 * math.pi * 2 + phase) * side)
        sx, sy = 350 + side * 150, 450
        ex, ey = sx + side * math.cos(ang) * 170, sy - math.sin(ang) * 170 * side
        d.line([(sx, sy), (ex, ey)], fill=brown, width=80)
        d.ellipse([ex - 42, ey - 42, ex + 42, ey + 42], fill=brown)
    d.ellipse([190, 380, 510, 720], fill=brown)          # cuerpo
    d.ellipse([260, 450, 440, 680], fill=light)          # panza
    d.ellipse([170, 80, 270, 180], fill=brown)           # orejas
    d.ellipse([430, 80, 530, 180], fill=brown)
    d.ellipse([195, 105, 245, 155], fill=light)
    d.ellipse([455, 105, 505, 155], fill=light)
    d.ellipse([200, 100, 500, 400], fill=brown)          # cabeza
    d.ellipse([290, 250, 410, 360], fill=light)          # hocico
    d.ellipse([325, 255, 375, 295], fill=dark)           # nariz
    d.arc([310, 270, 390, 340], 20, 160, fill=dark, width=8)
    blink = int(t * 20) % 20 == 0
    for ex in (290, 410):
        if blink:
            d.line([(ex - 22, 230), (ex + 22, 230)], fill=dark, width=8)
        else:
            d.ellipse([ex - 20, 205, ex + 20, 250], fill=dark)
            d.ellipse([ex - 8, 212, ex + 4, 226], fill=WHITE)
    d.ellipse([240, 280, 280, 310], fill=(255, 140, 160, 160))  # cachetes
    d.ellipse([420, 280, 460, 310], fill=(255, 140, 160, 160))
    bounce = abs(math.sin(t * 2 * math.pi * 2)) * 50
    paste_center(img, bear, S / 2, S * .55 - bounce, scale=1.0, angle=10 * math.sin(t * 2 * math.pi))
    d = ImageDraw.Draw(img)
    for i in range(4):
        p = (t * 2 + i / 4) % 1
        note(d, S * (.12 + .76 * (i % 2)), S * (.45 - p * .35), 34, PALETTE[i])
    return img


def cafe(t: float) -> Image.Image:
    img = blank()
    d = ImageDraw.Draw(img)
    cx, top = S / 2, S * .52
    d.ellipse([cx + 150, top + 70, cx + 330, top + 290], outline=(240, 240, 245, 255), width=48)  # asa
    d.rounded_rectangle([cx - 230, top, cx + 210, top + 380], radius=60, fill=(245, 245, 250, 255))
    d.rounded_rectangle([cx - 230, top + 150, cx + 210, top + 230], radius=10, fill=PINK)
    d.ellipse([cx - 230, top - 45, cx + 210, top + 45], fill=(245, 245, 250, 255))
    d.ellipse([cx - 200, top - 30, cx + 180, top + 30], fill=(110, 60, 30, 255))
    heart(d, cx - 10, top + 300, 70, PINK)
    for k in range(3):  # vapor
        pts = []
        for j in range(30):
            p = j / 29
            y = top - 60 - p * 360
            x = cx - 110 + k * 100 + math.sin(p * 9 + t * 2 * math.pi + k) * 30
            pts.append((x, y))
        d.line(pts, fill=(255, 255, 255, 170), width=22, joint="curve")
    return img


def ecualizador(t: float) -> Image.Image:
    img = blank()
    d = ImageDraw.Draw(img)
    n, w = 9, 70
    for i in range(n):
        h = (.25 + .7 * abs(math.sin(t * 2 * math.pi * (1 + i % 3) + i * 1.3))) * S * .55
        x = S / 2 + (i - (n - 1) / 2) * (w + 26)
        color = PALETTE[i % 3]
        d.rounded_rectangle([x - w / 2, S * .8 - h, x + w / 2, S * .8], radius=22, fill=color)
    return img


def platica(t: float) -> Image.Image:
    """Globos de diálogo que se turnan (para lives de plática)."""
    img = blank()
    d = ImageDraw.Draw(img)
    for k, (cx, cy, color, flip) in enumerate([(.38, .40, CYAN, 1), (.62, .62, PINK, -1)]):
        pop = max(0.0, min(1.0, math.sin(((t + k * .5) % 1) * math.pi) * 1.6))
        if pop < .05:
            continue
        w, h = S * .36 * pop, S * .24 * pop
        x, y = S * cx, S * cy
        d.rounded_rectangle([x - w / 2, y - h / 2, x + w / 2, y + h / 2], radius=int(60 * pop), fill=color)
        d.polygon([(x - flip * w * .2, y + h / 2 - 5), (x - flip * w * .38, y + h / 2 + 70 * pop), (x - flip * w * .02, y + h / 2 - 5)], fill=color)
        for j in range(3):  # puntitos
            r = 16 * pop * (1 + .35 * math.sin(t * 2 * math.pi * 3 + j))
            d.ellipse([x - 60 * pop + j * 60 * pop - r, y - r, x - 60 * pop + j * 60 * pop + r, y + r], fill=(20, 20, 30, 255))
    return img


BANK = {
    "corazones": corazones, "confeti": confeti, "fuegos-artificiales": fuegos, "estrellas": estrellas,
    "gracias": gracias, "thank-you": thanks("THANK YOU!"), "obrigado": thanks("OBRIGADO!"), "x2": multiplicador("x2"), "x3": multiplicador("x3"), "microfono-cantando": microfono,
    "osito-bailando": osito, "cafe-ya-regreso": cafe, "ecualizador": ecualizador, "platicando": platica,
}


if __name__ == "__main__":
    import sys

    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for name, fn in BANK.items():
        if only and name not in only:
            continue
        frames = [fn(i / FRAMES).resize((FINAL, FINAL), Image.LANCZOS) for i in range(FRAMES)]
        path = OUT / f"{name}.webp"
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=MS, loop=0, quality=82, method=4,
                       lossless=False, allow_mixed=True)
        print(f"{path.name}: {path.stat().st_size // 1024} KB")
