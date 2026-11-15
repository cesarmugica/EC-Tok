"""Genera el ícono de EC-Tok: una campana de alerta con destellos (colores rosa y turquesa)."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src" / "web" / "img"


def draw(size: int = 512) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=(22, 22, 30, 255))
    pink, cyan, white = (254, 44, 85, 255), (37, 244, 238, 255), (255, 255, 255, 255)

    def bell(dx: float, dy: float, color) -> None:
        cx, top = s * .5 + dx, s * .20 + dy
        d.ellipse([cx - s * .045, top - s * .045, cx + s * .045, top + s * .045], fill=color)
        d.pieslice([cx - s * .22, top, cx + s * .22, top + s * .44], 180, 360, fill=color)
        d.polygon([(cx - s * .22, top + s * .22), (cx + s * .22, top + s * .22), (cx + s * .29, top + s * .50),
                   (cx - s * .29, top + s * .50)], fill=color)
        d.rounded_rectangle([cx - s * .32, top + s * .48, cx + s * .32, top + s * .56], radius=int(s * .03), fill=color)
        d.ellipse([cx - s * .07, top + s * .55, cx + s * .07, top + s * .67], fill=color)

    bell(-s * .025, 0, cyan)       # sombra turquesa
    bell(s * .025, s * .01, pink)  # sombra rosa
    bell(0, 0, white)
    # destellos
    for (x, y, r) in ((.18, .26, .045), (.82, .22, .035), (.84, .66, .03)):
        cx, cy, rr = s * x, s * y, s * r
        d.polygon([(cx, cy - rr * 2), (cx + rr * .5, cy - rr * .5), (cx + rr * 2, cy), (cx + rr * .5, cy + rr * .5),
                   (cx, cy + rr * 2), (cx - rr * .5, cy + rr * .5), (cx - rr * 2, cy), (cx - rr * .5, cy - rr * .5)], fill=(255, 214, 0, 255))
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw(512)
    big.resize((192, 192), Image.LANCZOS).save(OUT / "ectok.png")
    big.save(OUT / "ectok.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("íconos en", OUT)
