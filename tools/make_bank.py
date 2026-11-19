"""Convierte los videos de ComfyUI (personajes con letrero en fondo verde y efectos en fondo negro)
al formato del banco de EC-Tok: WebM VP9 con transparencia + escenas.json con el letrero seguido cuadro por cuadro.

Uso:
  python3 make_bank.py personajes <carpeta con V1-brinco, V2-letrero-arriba, V3-baile-felicidad> <salida>
  python3 make_bank.py efecto <video.mp4> <salida> <Nombre-Del-Efecto> [verde|negro]

Personajes: «F-Dey» en «V1-brinco» → «Girl-Dey-Jumping.webm» (F=Girl, M=Boy, A=Pet;
V1=Jumping, V2=Sign-Up, V3=Happy-Dance). El letrero blanco se busca en cada cuadro y se guarda su
posición (centro x, centro y, ancho, alto en % del cuadro y giro en grados) para que EC-Tok escriba ahí el texto.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage as ndi

FPS = 16
VARIANTS = {"V1-brinco": "Jumping", "V2-letrero-arriba": "Sign-Up", "V3-baile-felicidad": "Happy-Dance"}
KINDS = {"F": "Girl", "M": "Boy", "A": "Pet"}


def frames(path: Path) -> list:
    cap, out = cv2.VideoCapture(str(path)), []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
    return out


def key_green(rgb: np.ndarray) -> np.ndarray:
    a = rgb.astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gx = g - np.maximum(r, b)
    al = np.clip(1 - (gx - 20) / (110 - 20), 0, 1)
    solid = al > 0.5
    lab, n = ndi.label(solid)
    if n:  # quitar manchitas sueltas
        sz = ndi.sum(solid, lab, range(1, n + 1))
        keep = np.isin(lab, [i + 1 for i, s in enumerate(sz) if s > 400])
        al = al * ndi.binary_dilation(keep, iterations=2)
    g2 = np.minimum(g, (r + b) / 2 + 12)  # quitar el reflejo verde de las orillas
    return np.dstack([r, g2, b, al * 255]).clip(0, 255).astype(np.uint8)


def key_black(rgb: np.ndarray) -> np.ndarray:
    """Luces sobre negro: la transparencia sale del brillo (lo negro desaparece, lo brillante queda)."""
    a = rgb.astype(float)
    al = a.max(axis=2)
    al = np.clip((al - 6) / (255 - 6), 0, 1)
    col = np.where(al[..., None] > 0.01, a / np.maximum(al[..., None], 1e-3), 0)
    return np.dstack([col.clip(0, 255), al * 255]).astype(np.uint8)


def _norm_rect(cx, cy, w, h, ang):
    if w < h:
        w, h = h, w
        ang += 90
    while ang > 45:
        ang -= 180
    while ang < -45:
        ang += 180
    return [cx, cy, w, h, ang]


def flat_white_box(rgba: np.ndarray):
    """El interior del letrero es blanco y LISO; el pelaje o las plumas blancas tienen textura.
    La envolvente convexa recupera las esquinas que tapan las patas o las manos."""
    rgb = rgba[..., :3].astype(np.float32)
    gray = rgb.mean(axis=2)
    mu = cv2.blur(gray, (7, 7))
    std = np.sqrt(np.maximum(cv2.blur(gray * gray, (7, 7)) - mu * mu, 0))
    flat = ((rgb.min(axis=2) > 205) & (std < 6) & (rgba[..., 3] > 200)).astype(np.uint8)
    flat = cv2.morphologyEx(flat, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(flat)
    if n < 2:
        return None
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    if st[i, cv2.CC_STAT_AREA] < 3000:
        return None
    cnts, _ = cv2.findContours((lab == i).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
    (cx, cy), (w, h), ang = cv2.minAreaRect(hull)
    box = _norm_rect(cx, cy, w, h, ang)
    if not 1.5 < box[2] / max(box[3], 1) < 3.0 or st[i, cv2.CC_STAT_AREA] < 0.6 * box[2] * box[3]:
        return None
    return box


def sign_box(rgba: np.ndarray):
    box = flat_white_box(rgba)
    if box:
        return box
    return _sign_box_frame(rgba)


def _sign_box_frame(rgba: np.ndarray):
    """Dónde está el letrero blanco. 1) la mancha blanca que de verdad sea un rectángulo;
    2) si el letrero se pega con pelaje o plumas blancas, se busca por su marco naranja
    (y se comprueba que por dentro sea blanco)."""
    r, g, b, a = [rgba[..., i].astype(int) for i in range(4)]
    white = ((r > 200) & (g > 200) & (b > 200) & (a > 200)).astype(np.uint8)
    white = cv2.morphologyEx(white, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    orange = ((r > 150) & (r - g > 40) & (g > 40) & (b < 130) & (a > 150)).astype(np.uint8)
    # marco naranja
    orange = cv2.morphologyEx(orange, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(orange)
    for i in sorted(range(1, n), key=lambda k: -st[k, cv2.CC_STAT_AREA])[:4]:
        if st[i, cv2.CC_STAT_AREA] < 800:
            break
        # Las patas o manos tapan las esquinas y el marco se parte en pedazos: juntar los pedazos de marco
        # que estén alrededor del pedazo más grande (hasta 45 % de su ancho arriba y abajo).
        x, y, w0, h0 = st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP], st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        pad = int(w0 * 0.45)
        keep = np.zeros(lab.shape, bool)
        for j in range(1, n):
            if st[j, cv2.CC_STAT_AREA] < 60:
                continue
            jx, jy, jw, jh = st[j, cv2.CC_STAT_LEFT], st[j, cv2.CC_STAT_TOP], st[j, cv2.CC_STAT_WIDTH], st[j, cv2.CC_STAT_HEIGHT]
            if jx >= x - 10 and jx + jw <= x + w0 + 10 and jy >= y - pad and jy + jh <= y + h0 + pad:
                keep |= lab == j
        ys, xs = np.where(keep)
        (cx, cy), (w, h), ang = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        box = _norm_rect(cx, cy, w, h, ang)
        if not 1.5 < box[2] / max(box[3], 1) < 3.4:
            continue
        inner = np.zeros(white.shape, np.uint8)
        pts = cv2.boxPoints(((box[0], box[1]), (box[2] * 0.8, box[3] * 0.7), box[4])).astype(np.int32)
        cv2.fillPoly(inner, [pts], 1)
        if inner.any() and white[inner > 0].mean() > 0.45:
            return [box[0], box[1], box[2] * 0.94, box[3] * 0.88, box[4]]  # por dentro del marco
    n, lab, st, _ = cv2.connectedComponentsWithStats(white)
    for i in sorted(range(1, n), key=lambda k: -st[k, cv2.CC_STAT_AREA])[:6]:
        area = st[i, cv2.CC_STAT_AREA]
        if area < 1500:
            break
        mask = (lab == i).astype(np.uint8)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        (cx, cy), (w, h), ang = cv2.minAreaRect(max(cnts, key=cv2.contourArea))
        box = _norm_rect(cx, cy, w, h, ang)
        ring = cv2.dilate(mask, np.ones((9, 9), np.uint8)) - mask
        framed = orange[ring > 0].mean() if ring.any() else 0
        if area / max(w * h, 1) >= 0.78 and 1.15 < box[2] / max(box[3], 1) < 4.5 and framed >= 0.12:
            return box
    return None


def crop_box(rgbas: list, margin: float = 0.02):
    al = np.max([x[..., 3] for x in rgbas], axis=0)
    ys, xs = np.where(al > 8)
    H, W = al.shape
    mx, my = int(W * margin), int(H * margin)
    x0, x1 = max(0, xs.min() - mx), min(W, xs.max() + 1 + mx)
    y0, y1 = max(0, ys.min() - my), min(H, ys.max() + 1 + my)
    # VP9 con yuva420p pide medidas pares
    x1 -= (x1 - x0) % 2
    y1 -= (y1 - y0) % 2
    return x0, y0, x1, y1


def encode(rgbas: list, box, out: Path, crf: int = 34) -> None:
    x0, y0, x1, y1 = box
    with tempfile.TemporaryDirectory() as tmp:
        for i, f in enumerate(rgbas):
            cv2.imwrite(os.path.join(tmp, f"{i:04d}.png"), cv2.cvtColor(np.ascontiguousarray(f[y0:y1, x0:x1]), cv2.COLOR_RGBA2BGRA))
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", os.path.join(tmp, "%04d.png"),
                        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", str(crf), "-row-mt", "1",
                        "-auto-alt-ref", "0", "-deadline", "good", "-cpu-used", "2", str(out)], check=True)


def trim_reappear(rgbas: list) -> list:
    """Si al final el modelo vuelve a dibujar la imagen de inicio, cortar en el momento más vacío."""
    cover = [float((x[..., 3] > 30).mean()) for x in rgbas]
    start = len(rgbas) // 2
    imin = min(range(start, len(rgbas)), key=lambda i: cover[i])
    if imin < len(rgbas) - 1 and max(cover[imin:]) > cover[imin] * 1.5 + 0.004:
        rgbas = rgbas[: imin + 1]
    # medio segundo de desvanecido al final
    n = min(8, len(rgbas))
    for k in range(n):
        f = rgbas[-n + k].copy()
        f[..., 3] = (f[..., 3].astype(float) * (n - 1 - k) / n).astype(np.uint8)
        rgbas[-n + k] = f
    return rgbas


def _smooth_detections(rgbas: list, boxes: list, smooth: bool = True) -> np.ndarray:
    """Respaldo: las detecciones cuadro por cuadro, sin cuadros sueltos raros y suavizadas."""
    good = [b for b in boxes if b]
    last = good[0]
    boxes = list(boxes)
    for i, b in enumerate(boxes):  # cuadros donde una mano tapa el letrero: usar el anterior
        boxes[i] = last = b or last
    B = np.array(boxes, float)
    H = rgbas[0].shape[0]
    med = np.array([np.median(B[max(0, i - 3): i + 4], axis=0) for i in range(len(B))])
    bad = (np.abs(B[:, 1] - med[:, 1]) > H * 0.08) | (np.abs(B[:, 2] - med[:, 2]) > med[:, 2] * 0.25)
    B[bad] = med[bad]
    if not smooth:
        return B
    from scipy.signal import savgol_filter
    n = len(B)
    for j, win in ((0, 9), (1, 9), (2, 15), (3, 15), (4, 11)):
        win = min(win, n - (1 - n % 2))
        if win >= 5:
            B[:, j] = savgol_filter(B[:, j], win, 2, mode="nearest")
    return B


def track_board(rgbas: list, boxes: list):
    """Sigue el letrero «pegado» sin atraso y sin temblor. Se combinan dos cosas:
    - el movimiento exacto del letrero entre un cuadro y el siguiente (ECC, precisión de subpíxel), que da el «pegado»;
    - la detección del letrero en cada cuadro, que evita que se vaya desviando.
    Se resuelve todo junto por mínimos cuadrados (sin suavizar en el tiempo, así no se atrasa en los brincos)."""
    from scipy.sparse import diags
    from scipy.sparse.linalg import spsolve
    n = len(rgbas)
    clean = _smooth_detections(rgbas, boxes, smooth=False)  # detecciones sin cuadros sueltos raros (sin suavizar)
    has = np.array([b is not None for b in boxes])
    ok = np.flatnonzero(has)
    aspect = float(np.median([boxes[i][2] / boxes[i][3] for i in ok]))
    S = 0.5
    gray = [cv2.GaussianBlur(cv2.resize(cv2.cvtColor(np.ascontiguousarray(x[..., :3]), cv2.COLOR_RGB2GRAY), None, fx=S, fy=S,
                                        interpolation=cv2.INTER_AREA), (3, 3), 0).astype(np.float32) for x in rgbas]
    Hh, Ww = gray[0].shape
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5)
    # movimiento entre cuadros consecutivos: d[i] = (dx, dy, log escala, giro) de i-1 a i
    mot = np.zeros((n, 4))
    good = np.zeros(n, bool)
    for i in range(1, n):
        cx, cy, w, h, a = clean[i - 1]
        m = np.zeros((Hh, Ww), np.uint8)
        cv2.fillPoly(m, [cv2.boxPoints(((cx * S, cy * S), (w * S * 1.05, w / aspect * S * 1.1), a)).astype(np.int32)], 255)
        c2 = clean[i]
        t0 = np.array([[1, 0, (c2[0] - cx) * S], [0, 1, (c2[1] - cy) * S]], np.float32)
        best, bcc = None, 0.0
        for init in (np.eye(2, 3, dtype=np.float32), t0):
            try:
                cc, M = cv2.findTransformECC(gray[i - 1], gray[i], init.copy(), cv2.MOTION_AFFINE, crit, m, 1)
            except cv2.error:
                continue
            if cc > bcc:
                best, bcc = M, cc
        if best is None or bcc < 0.85:
            continue
        ar = np.radians(a)
        c = best @ np.array([cx * S, cy * S, 1.0]) / S
        ux = best[:, :2] @ np.array([np.cos(ar), np.sin(ar)])
        sc = np.linalg.norm(ux)
        if abs(np.log(sc)) > 0.15:
            continue
        mv = [c[0] - cx, c[1] - cy, np.log(sc), np.degrees(np.arctan2(ux[1], ux[0])) - a]
        if has[i] and has[i - 1]:  # en movimientos muy rápidos ECC puede equivocarse: debe cuadrar con lo detectado
            dd = [c2[0] - cx, c2[1] - cy, np.log(c2[2] / w), c2[4] - a]
            if np.hypot(mv[0] - dd[0], mv[1] - dd[1]) > 0.04 * w or abs(mv[2] - dd[2]) > 0.06 or abs(mv[3] - dd[3]) > 3:
                continue
        mot[i] = mv
        good[i] = True
    # mínimos cuadrados: wd·(p_i − det_i)² + wm·(p_i − p_{i−1} − mov_i)²
    det = np.c_[clean[:, 0], clean[:, 1], np.log(clean[:, 2]), clean[:, 4]]
    out = np.zeros((n, 4))
    wm = np.where(good, 60.0, 0.0)
    wd = np.where(has, 1.0, 0.0)
    if not wd.any():
        wd[:] = 1.0
    for j in range(4):
        wmj = wm.copy()
        for _ in range(4):  # los movimientos que no cuadran con las detecciones pesan menos
            main = wd.copy()
            main[1:] += wmj[1:]
            main[:-1] += wmj[1:]
            A = diags([main + 1e-9, -wmj[1:], -wmj[1:]], [0, -1, 1], format="csc")
            rhs = wd * det[:, j]
            rhs[1:] += wmj[1:] * mot[1:, j]
            rhs[:-1] -= wmj[1:] * mot[1:, j]
            x = spsolve(A, rhs)
            r = np.abs(np.diff(x) - mot[1:, j])
            tol = {0: 0.004 * clean[1:, 2], 1: 0.004 * clean[1:, 2], 2: np.full(n - 1, 0.005), 3: np.full(n - 1, 0.2)}[j]
            wmj[1:] = wm[1:] * np.where(r > tol, (tol / np.maximum(r, 1e-9)) ** 2, 1.0)
        out[:, j] = x
    w = np.exp(out[:, 2])
    return np.c_[out[:, 0], out[:, 1], w, w / aspect, out[:, 3]]


def character(src: Path, out_dir: Path, name: str) -> dict:
    rgbas = [key_green(f) for f in frames(src)]
    boxes = [sign_box(x) for x in rgbas]
    if not any(boxes):
        raise RuntimeError(f"{src}: no encontré el letrero")
    B = track_board(rgbas, boxes)
    box = crop_box(rgbas)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    track = [[round((cx - x0) / w * 100, 2), round((cy - y0) / h * 100, 2), round(bw / w * 100, 2), round(bh / h * 100, 2), round(a, 1)]
             for cx, cy, bw, bh, a in B]
    file = f"{name}.webm"
    encode(rgbas, box, out_dir / file)
    return {file: {"ratio": round(w / h, 4), "video": {"fps": FPS}, "track": track, "parts": []}}


def whiten_steam(rgb: np.ndarray, rgba: np.ndarray) -> np.ndarray:
    """Vapor sobre verde: en el original es blanco-verdoso y al quitar el verde casi desaparece.
    Lo blanquecino (rojo y azul altos aunque el verde domine) se recupera como vapor blanco semitransparente,
    solo lejos de las orillas de los objetos sólidos para no hacer halos."""
    a = rgb.astype(float)
    rb = np.minimum(a[..., 0], a[..., 2])
    steam_al = np.clip((rb - 40) / 170, 0, 1) * 0.9
    al = rgba[..., 3].astype(float) / 255
    solid = (al > 0.9).astype(np.uint8)
    far = cv2.distanceTransform(1 - solid, cv2.DIST_L2, 3) > 5
    use = far & (steam_al > al)
    out = rgba.copy()
    out[use, 0:3] = 245
    out[use, 3] = (steam_al[use] * 255).astype(np.uint8)
    return out


def effect(src: Path, out_dir: Path, name: str, bg: str = "negro") -> str:
    rgbas = [] if bg == "vapor" else [(key_black if bg == "negro" else key_green)(f) for f in frames(src)]
    if bg == "vapor":  # fondo verde con vapor (tazas de café)
        rgbas = [whiten_steam(f, key_green(f)) for f in frames(src)]
    if bg == "negro":
        rgbas = trim_reappear(rgbas)
    box = crop_box(rgbas, 0.01)
    file = f"{name}.webm"
    encode(rgbas, box, out_dir / file, crf=38)
    return file


def main() -> None:
    mode, src, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    if mode == "personajes":
        scenes_path = out / "escenas.json"
        scenes = json.loads(scenes_path.read_text(encoding="utf-8")) if scenes_path.exists() else {}
        only = set(sys.argv[4:])
        for folder, verb in VARIANTS.items():
            for mp4 in sorted((src / folder).glob("*_00001_.mp4")):
                stem = mp4.name.split("_")[0]
                if "-" not in stem:
                    continue
                code, person = stem.split("-", 1)
                name = f"{KINDS.get(code, 'Pet')}-{person}-{verb}"
                if only and name not in only and person not in only:
                    continue
                if (out / f"{name}.webm").exists() and f"{name}.webm" in scenes:
                    continue
                scenes.update(character(mp4, out, name))
                scenes_path.write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
                print(name, (out / f"{name}.webm").stat().st_size // 1024, "KB", flush=True)
    else:
        print(effect(src, out, sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else "negro"))


if __name__ == "__main__":
    main()
