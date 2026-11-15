"""EC-Tok — alertas, sonidos, lectura de chat y metas para tus lives de TikTok (gratis).

Servidor local (solo 127.0.0.1):
- «/»          la ventana de EC-Tok (conexión, alertas, sonidos, voz, metas).
- «/overlay»   las páginas transparentes para TikTok LIVE Studio u OBS:
               /overlay?w=alerts · /overlay?w=goal · /overlay?w=top
- «/api/stream» los eventos del live en tiempo real (Server-Sent Events).
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import mimetypes
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

APP_VERSION = "1.1.1"

try:  # lo genera windows/build.ps1
    from ectok_build import BUILD_DATE  # type: ignore[import-not-found]
except ImportError:
    BUILD_DATE = ""

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
WEB_ROOT = ROOT / "web"
DEFAULT_PORT = 8795
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
IS_WINDOWS = os.name == "nt"


def ectok_home() -> Path:
    override = os.environ.get("ECTOK_HOME")
    if override:
        return Path(override)
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "EC-Tok"
    return Path.home() / ".local" / "state" / "ectok"


HOME = ectok_home()
SOUNDS_DIR = HOME / "sounds"
ANIM_USER = HOME / "animaciones"     # las tuyas (GIF, WebP, APNG o WebM con transparencia)
ANIM_DEFAULT = WEB_ROOT / "anim"     # las que trae EC-Tok
ANIM_EXTS = {".gif": "image/gif", ".webp": "image/webp", ".png": "image/png", ".apng": "image/apng", ".webm": "video/webm"}


def _setup_logging() -> None:
    if sys.stdout is not None and not getattr(sys, "frozen", False):
        return
    log_dir = HOME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "ectok.log"
    with contextlib.suppress(OSError):
        if log_path.exists() and log_path.stat().st_size > 2 * 1024 * 1024:
            log_path.replace(log_dir / "ectok.old.log")
    stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = stream


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if IS_WINDOWS else 0


_setup_logging()


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


# ---------------------------------------------------------------------------
# Ajustes
# ---------------------------------------------------------------------------
CONFIG_PATH = HOME / "config.json"
CONFIG_LOCK = threading.Lock()
DEFAULT_CONFIG: dict = {
    "username": "",
    "euler_key": "",
    "autoconnect": False,
    "alerts": {
        "gift": {"on": True, "min_diamonds": 1, "text": "{user} envió {count}× {gift}", "seconds": 6},
        "follow": {"on": True, "text": "{user} te empezó a seguir", "seconds": 4},
        "share": {"on": True, "text": "{user} compartió el live", "seconds": 4},
        "like": {"on": False, "every": 1000, "text": "¡Ya llevamos {likes} likes!", "seconds": 4},
    },
    "style": {"color": "#FE2C55", "accent": "#25F4EE", "font_size": 34, "animation": "pop", "position": "top"},
    "sounds": [],  # [{id, on, trigger: any_gift|gift|min_diamonds|follow|share|likes, gift, min_diamonds, every, file, name, volume}]
    "sound_overlap": False,
    "tts": {"on": False, "comments": True, "gifts": True, "follows": False, "shares": False, "voice": "",
            "rate": 1.0, "volume": 1.0, "pitch": 1.0, "max_chars": 120, "skip_links": True, "prefix": "",
            "comment_text": "{user} dice: {text}", "gift_text": "{user} envió {count} {gift}. ¡Gracias!",
            "follow_text": "Gracias por seguirme, {user}", "share_text": "Gracias por compartir, {user}"},
    "goals": [{"id": "likes", "on": True, "kind": "likes", "target": 10000, "title": "Meta de likes"}],
    "top": {"count": 5, "title": "Top donadores"},
    "anims": {
        # trigger: any_gift | gift | min_diamonds | follow | share | likes | subscribe | superfan | envelope |
        #          battle_start | battle_end | booster
        "rules": [
            {"id": "heartme", "on": True, "trigger": "gift", "gift": "Heart Me", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "corazones.webp", "seconds": 4, "size": 70},
            {"id": "follow", "on": True, "trigger": "follow", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "gracias.webp", "seconds": 3, "size": 60},
            {"id": "big", "on": True, "trigger": "min_diamonds", "gift": "", "min_diamonds": 1000, "every": 1000, "multiplier": 0,
             "file": "fuegos-artificiales.webp", "seconds": 5, "size": 90},
            {"id": "chest", "on": True, "trigger": "envelope", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "confeti.webp", "seconds": 4, "size": 90},
            {"id": "sub", "on": True, "trigger": "subscribe", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "estrellas.webp", "seconds": 4, "size": 80},
            {"id": "x2", "on": True, "trigger": "booster", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 2,
             "file": "x2.webp", "seconds": 4, "size": 70},
            {"id": "x3", "on": True, "trigger": "booster", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 3,
             "file": "x3.webp", "seconds": 4, "size": 70},
        ],
        "quick": [
            {"id": "q1", "label": "Corazones", "file": "corazones.webp"}, {"id": "q2", "label": "Confeti", "file": "confeti.webp"},
            {"id": "q3", "label": "¡Gracias!", "file": "gracias.webp"}, {"id": "q4", "label": "x2", "file": "x2.webp"},
            {"id": "q5", "label": "x3", "file": "x3.webp"}, {"id": "q6", "label": "Fuegos", "file": "fuegos-artificiales.webp"},
        ],
        "quick_seconds": 4,
        "quick_size": 70,
        "brb": {"file": "cafe-ya-regreso.webp", "text": "Ya regresamos", "sub": "No te vayas 💖", "dim": True},
    },
    "language": "es",
}


def _merge(base: dict, saved: dict) -> dict:
    out = {}
    for key, value in base.items():
        if isinstance(value, dict) and isinstance(saved.get(key), dict):
            out[key] = _merge(value, saved[key])
        elif key in saved and (type(saved[key]) is type(value) or (isinstance(value, float) and isinstance(saved[key], int))):
            out[key] = saved[key]
        else:
            out[key] = json.loads(json.dumps(value))
    return out


def load_config() -> dict:
    with contextlib.suppress(OSError, json.JSONDecodeError):
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            return _merge(DEFAULT_CONFIG, saved)
    return _merge(DEFAULT_CONFIG, {})


def save_config(config: dict) -> None:
    with CONFIG_LOCK:
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(CONFIG_PATH)


CONFIG = load_config()
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _text(value, default: str, limit: int = 200) -> str:
    return str(value)[:limit] if isinstance(value, str) else default


def _num(value, default, lo, hi):
    return min(hi, max(lo, value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def clean_config(data: dict) -> dict:
    """Validar lo que manda la ventana (solo se guardan datos conocidos y razonables)."""
    cfg = load_config()
    if "username" in data:
        cfg["username"] = _text(data["username"], "", 60).strip().lstrip("@")
    if "euler_key" in data:
        cfg["euler_key"] = _text(data["euler_key"], "", 200).strip()
    if isinstance(data.get("autoconnect"), bool):
        cfg["autoconnect"] = data["autoconnect"]
    if data.get("language") in ("es", "en"):
        cfg["language"] = data["language"]
    alerts = data.get("alerts")
    if isinstance(alerts, dict):
        for kind, current in cfg["alerts"].items():
            new = alerts.get(kind)
            if isinstance(new, dict):
                if isinstance(new.get("on"), bool):
                    current["on"] = new["on"]
                current["text"] = _text(new.get("text"), current["text"], 120)
                current["seconds"] = _num(new.get("seconds"), current["seconds"], 1, 30)
                if "min_diamonds" in current:
                    current["min_diamonds"] = int(_num(new.get("min_diamonds"), current["min_diamonds"], 0, 100000))
                if "every" in current:
                    current["every"] = int(_num(new.get("every"), current["every"], 10, 10_000_000))
    style = data.get("style")
    if isinstance(style, dict):
        s = cfg["style"]
        for key in ("color", "accent"):
            if HEX.fullmatch(str(style.get(key) or "")):
                s[key] = style[key]
        s["font_size"] = int(_num(style.get("font_size"), s["font_size"], 16, 90))
        if style.get("animation") in ("pop", "slide", "bounce", "fade"):
            s["animation"] = style["animation"]
        if style.get("position") in ("top", "center", "bottom"):
            s["position"] = style["position"]
    if isinstance(data.get("sounds"), list):
        rules = []
        for rule in data["sounds"][:100]:
            if not isinstance(rule, dict) or rule.get("trigger") not in ("any_gift", "gift", "min_diamonds", "follow", "share", "likes"):
                continue
            file = Path(str(rule.get("file") or "")).name
            rules.append({"id": _text(rule.get("id"), uuid.uuid4().hex[:8], 20), "on": rule.get("on") is not False,
                          "trigger": rule["trigger"], "gift": _text(rule.get("gift"), "", 60).strip(),
                          "min_diamonds": int(_num(rule.get("min_diamonds"), 1, 0, 1_000_000)),
                          "every": int(_num(rule.get("every"), 500, 10, 10_000_000)),
                          "file": file, "name": _text(rule.get("name"), file, 120),
                          "volume": int(_num(rule.get("volume"), 80, 0, 100))})
        cfg["sounds"] = rules
    if isinstance(data.get("sound_overlap"), bool):
        cfg["sound_overlap"] = data["sound_overlap"]
    tts = data.get("tts")
    if isinstance(tts, dict):
        t = cfg["tts"]
        for key in ("on", "comments", "gifts", "follows", "shares", "skip_links"):
            if isinstance(tts.get(key), bool):
                t[key] = tts[key]
        t["voice"] = _text(tts.get("voice"), t["voice"], 120)
        t["prefix"] = _text(tts.get("prefix"), t["prefix"], 10)
        for key in ("comment_text", "gift_text", "follow_text", "share_text"):
            t[key] = _text(tts.get(key), t[key], 120)
        t["rate"] = float(_num(tts.get("rate"), t["rate"], 0.5, 2.0))
        t["pitch"] = float(_num(tts.get("pitch"), t["pitch"], 0.5, 2.0))
        t["volume"] = float(_num(tts.get("volume"), t["volume"], 0.0, 1.0))
        t["max_chars"] = int(_num(tts.get("max_chars"), t["max_chars"], 20, 300))
    if isinstance(data.get("goals"), list):
        goals = []
        for goal in data["goals"][:6]:
            if isinstance(goal, dict) and goal.get("kind") in ("likes", "diamonds", "follows", "shares", "gifts"):
                goals.append({"id": _text(goal.get("id"), uuid.uuid4().hex[:8], 20), "on": goal.get("on") is not False,
                              "kind": goal["kind"], "target": int(_num(goal.get("target"), 100, 1, 1_000_000_000)),
                              "title": _text(goal.get("title"), "Meta", 60)})
        cfg["goals"] = goals
    anims = data.get("anims")
    if isinstance(anims, dict):
        a = cfg["anims"]
        triggers = ("any_gift", "gift", "min_diamonds", "follow", "share", "likes", "subscribe", "superfan", "envelope",
                    "battle_start", "battle_end", "booster")
        if isinstance(anims.get("rules"), list):
            rules = []
            for r in anims["rules"][:60]:
                if isinstance(r, dict) and r.get("trigger") in triggers:
                    rules.append({"id": _text(r.get("id"), uuid.uuid4().hex[:8], 20), "on": r.get("on") is not False,
                                  "trigger": r["trigger"], "gift": _text(r.get("gift"), "", 60).strip(),
                                  "min_diamonds": int(_num(r.get("min_diamonds"), 1, 0, 1_000_000)),
                                  "every": int(_num(r.get("every"), 1000, 10, 10_000_000)),
                                  "multiplier": int(_num(r.get("multiplier"), 0, 0, 5)),
                                  "file": Path(str(r.get("file") or "")).name, "seconds": float(_num(r.get("seconds"), 4, 1, 30)),
                                  "size": int(_num(r.get("size"), 70, 10, 100))})
            a["rules"] = rules
        if isinstance(anims.get("quick"), list):
            a["quick"] = [{"id": _text(q.get("id"), uuid.uuid4().hex[:8], 20), "label": _text(q.get("label"), "Animación", 30),
                           "file": Path(str(q.get("file") or "")).name} for q in anims["quick"][:12] if isinstance(q, dict)]
        a["quick_seconds"] = float(_num(anims.get("quick_seconds"), a["quick_seconds"], 1, 30))
        a["quick_size"] = int(_num(anims.get("quick_size"), a["quick_size"], 10, 100))
        brb = anims.get("brb")
        if isinstance(brb, dict):
            a["brb"]["file"] = Path(str(brb.get("file") or a["brb"]["file"])).name
            a["brb"]["text"] = _text(brb.get("text"), a["brb"]["text"], 60)
            a["brb"]["sub"] = _text(brb.get("sub"), a["brb"]["sub"], 80)
            if isinstance(brb.get("dim"), bool):
                a["brb"]["dim"] = brb["dim"]
    top = data.get("top")
    if isinstance(top, dict):
        cfg["top"]["count"] = int(_num(top.get("count"), cfg["top"]["count"], 1, 10))
        cfg["top"]["title"] = _text(top.get("title"), cfg["top"]["title"], 60)
    return cfg


# ---------------------------------------------------------------------------
# Eventos en vivo para la ventana y los overlays (Server-Sent Events)
# ---------------------------------------------------------------------------
class Bus:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.subs: dict[int, tuple[str, queue.Queue]] = {}
        self.next_id = 1

    def subscribe(self, who: str) -> tuple[int, queue.Queue]:
        with self.lock:
            sid = self.next_id
            self.next_id += 1
            q: queue.Queue = queue.Queue(maxsize=500)
            self.subs[sid] = (who, q)
            return sid, q

    def unsubscribe(self, sid: int) -> None:
        with self.lock:
            self.subs.pop(sid, None)

    def emit(self, event: dict) -> None:
        with self.lock:
            targets = list(self.subs.values())
        for _who, q in targets:
            with contextlib.suppress(queue.Full):
                q.put_nowait(event)

    def count(self, who: str | None = None) -> int:
        with self.lock:
            return sum(1 for w, _q in self.subs.values() if who is None or w == who)


BUS = Bus()

from ectok_live import Live, new_event, test_event  # noqa: E402

# ---------------------------------------------------------------------------
# Animaciones: banco (las de EC-Tok + las tuyas), reglas automáticas y «ya regresamos»
# ---------------------------------------------------------------------------
BRB = {"on": False}
LIKE_MARKS: dict[str, int] = {}


def list_animations() -> list[dict]:
    found: dict[str, dict] = {}
    for folder, source in ((ANIM_DEFAULT, "ec-tok"), (ANIM_USER, "tuya")):
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in ANIM_EXTS:
                    found[path.name] = {"file": path.name, "name": path.stem.replace("-", " ").replace("_", " "),
                                        "source": source, "video": path.suffix.lower() == ".webm"}
    return sorted(found.values(), key=lambda a: (a["source"] != "tuya", a["name"]))


def anim_path(name: str) -> Path | None:
    name = Path(name).name
    for folder in (ANIM_USER, ANIM_DEFAULT):
        target = folder / name
        if target.is_file() and target.suffix.lower() in ANIM_EXTS:
            return target
    return None


def anim_event(file: str, seconds: float, size: int, label: str = "", manual: bool = False) -> dict:
    return new_event("anim", file=file, video=file.lower().endswith(".webm"), seconds=seconds, size=size,
                     label=label, manual=manual)


def anims_for(ev: dict) -> list[dict]:
    """Qué animación toca con este evento (la regla más específica gana)."""
    rules = [r for r in CONFIG["anims"]["rules"] if r["on"] and r["file"]]
    kind, chosen = ev.get("type"), []
    if kind == "gift":
        gift = ev["gift"]
        exact = [r for r in rules if r["trigger"] == "gift" and r["gift"].lower() == gift["name"].lower()]
        by_min = sorted([r for r in rules if r["trigger"] == "min_diamonds" and gift["total"] >= r["min_diamonds"]],
                        key=lambda r: r["min_diamonds"], reverse=True)
        anyg = [r for r in rules if r["trigger"] == "any_gift"]
        chosen = (exact or by_min or anyg)[:1]
    elif kind in ("follow", "share", "subscribe", "superfan", "envelope"):
        chosen = [r for r in rules if r["trigger"] == kind][:1]
    elif kind == "battle":
        chosen = [r for r in rules if r["trigger"] == "battle_" + ev.get("phase", "start")][:1]
    elif kind == "booster":
        mult = ev.get("multiplier") or 0
        exact = [r for r in rules if r["trigger"] == "booster" and r["multiplier"] == mult and mult]
        chosen = (exact or [r for r in rules if r["trigger"] == "booster" and not r["multiplier"]])[:1]
    elif kind == "like":
        likes = LIVE.stats.likes
        for r in rules:
            if r["trigger"] == "likes":
                mark = likes // r["every"] * r["every"]
                if r["id"] not in LIKE_MARKS:
                    LIKE_MARKS[r["id"]] = mark  # empezar a contar desde donde va el live
                elif mark > LIKE_MARKS[r["id"]]:
                    LIKE_MARKS[r["id"]] = mark
                    chosen.append(r)
    return [anim_event(r["file"], r["seconds"], r["size"], manual=False) for r in chosen]


def live_emit(event: dict) -> None:
    BUS.emit(event)
    if event.get("type") in ("gift", "follow", "share", "like", "subscribe", "superfan", "envelope", "battle", "booster"):
        for anim in anims_for(event):
            BUS.emit(anim)


LIVE = Live(emit=live_emit, log=log)


def overlay_payload() -> dict:
    """Lo que necesitan los overlays: estilos, alertas, metas y el estado del live."""
    return {"style": CONFIG["style"], "alerts": CONFIG["alerts"], "goals": CONFIG["goals"], "top": CONFIG["top"],
            "stats": LIVE.stats.public(CONFIG["top"]["count"]), "brb": {**CONFIG["anims"]["brb"], **BRB}}


# ---------------------------------------------------------------------------
# Sonidos (se copian a %LOCALAPPDATA%\EC-Tok\sounds para que no se pierdan)
# ---------------------------------------------------------------------------
SOUND_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".flac", ".webm"}
PICK_LOCK = threading.Lock()


def pick_sound() -> str | None:
    if not IS_WINDOWS:
        return None
    patterns = ";".join("*" + ext for ext in sorted(SOUND_EXTS))
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0; StartPosition='CenterScreen'}; $owner.Show(); $owner.Activate();"
        "$d = New-Object System.Windows.Forms.OpenFileDialog;"
        "$d.Title = 'Elige el sonido';"
        f"$d.Filter = 'Sonidos|{patterns}|Todos los archivos|*.*';"
        f"$d.InitialDirectory = '{str(Path.home() / 'Music').replace(chr(39), chr(39) * 2)}';"
        "if ($d.ShowDialog($owner) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.FileName }"
    )
    with PICK_LOCK:
        result = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=_no_window_flags(), timeout=600)
    chosen = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    return chosen or None


def import_sound(path: Path) -> dict:
    if path.suffix.lower() not in SOUND_EXTS:
        raise ValueError("Ese archivo no es un sonido compatible (mp3, wav, ogg, m4a…).")
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("El sonido pesa más de 30 MB; usa uno más corto.")
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-. ()]+", "_", path.stem)[:60] or "sonido"
    target = SOUNDS_DIR / f"{safe}{path.suffix.lower()}"
    n = 2
    while target.exists() and target.stat().st_size != path.stat().st_size:
        target = SOUNDS_DIR / f"{safe} ({n}){path.suffix.lower()}"
        n += 1
    if not target.exists():
        shutil.copy2(path, target)
    return {"file": target.name, "name": path.stem}


def open_in_explorer(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path)])


# ---------------------------------------------------------------------------
# Ventana
# ---------------------------------------------------------------------------
def _app_browser() -> str | None:
    if not IS_WINDOWS:
        return shutil.which("chromium") or shutil.which("google-chrome")
    bases = [os.environ.get(name) for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for rel in (Path("Microsoft/Edge/Application/msedge.exe"), Path("Google/Chrome/Application/chrome.exe")):
        for base in bases:
            if base and (Path(base) / rel).is_file():
                return str(Path(base) / rel)
    return None


def open_app_window(url: str) -> None:
    browser = _app_browser()
    if browser:
        with contextlib.suppress(OSError):
            # Sin «autoplay policy»: la ventana tiene que poder sonar alertas y leer el chat sin que des clic.
            subprocess.Popen([browser, f"--app={url}", "--window-size=1180,860",
                              "--autoplay-policy=no-user-gesture-required"], close_fds=True)
            return
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Servidor HTTP
# ---------------------------------------------------------------------------
LAST_PING = time.time()
IDLE_EXIT_SECONDS = 120


class Handler(BaseHTTPRequestHandler):
    port = DEFAULT_PORT
    server_version = "EC-Tok"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
        text = fmt % args
        if any(x in text for x in ("/api/ping", "/api/stream", "/sound/", "/img/", "/anim/", '"GET /overlay', "/api/state")):
            return
        log("HTTP " + text)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _local_request(self) -> bool:
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
        except ValueError:
            return False
        host = urlsplit("//" + (self.headers.get("Host") or "")).hostname or ""
        return host.lower() in LOCAL_HOSTS

    def _same_origin_post(self) -> bool:
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parts = urlsplit(origin)
        return (parts.hostname or "").lower() in LOCAL_HOSTS and parts.port == self.port

    def send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, data: bytes | None = None) -> None:
        data = path.read_bytes() if data is None else data
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if path.suffix == ".html":
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' https: data:; media-src 'self' blob:; "
                             "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2 * 1024 * 1024:
            raise ValueError("demasiado grande")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON inválido")
        return data

    # ---------- GET ----------
    def do_GET(self) -> None:  # noqa: N802
        global LAST_PING
        if not self._local_request():
            self.send_error(403)
            return
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path in ("/", "/index.html"):
            self.send_file(WEB_ROOT / "index.html")
        elif path in ("/overlay", "/overlay.html"):
            self.send_file(WEB_ROOT / "overlay.html")
        elif path.startswith("/img/") and re.fullmatch(r"/img/[\w.-]+", path):
            target = WEB_ROOT / "img" / path.rsplit("/", 1)[-1]
            if target.is_file():
                self.send_file(target)
            else:
                self.send_error(404)
        elif path.startswith("/anim/"):
            target = anim_path(unquote(path[len("/anim/"):]))
            if target:
                self._send_bytes(target, ANIM_EXTS[target.suffix.lower()])
            else:
                self.send_error(404)
        elif path == "/api/animations":
            self.send_json({"ok": True, "animations": list_animations()})
        elif path.startswith("/sound/"):
            self._send_sound(unquote(path[len("/sound/"):]))
        elif path == "/api/info":
            LAST_PING = time.time()
            self.send_json({"version": APP_VERSION, "build_date": BUILD_DATE, "config": CONFIG, "brb": BRB,
                            "animations": list_animations(),
                            "live": LIVE.public(CONFIG["top"]["count"]), "port": self.port,
                            "recent": list(LIVE.recent)[-60:]})
        elif path == "/api/overlay":
            self.send_json(overlay_payload())
        elif path == "/api/state":
            LAST_PING = time.time()
            self.send_json(LIVE.public(CONFIG["top"]["count"]))
        elif path == "/api/ping":
            LAST_PING = time.time()
            self.send_json({"ok": True})
        elif path == "/api/stream":
            self._stream(query.get("who", ["panel"])[0][:20])
        elif path == "/api/update":
            self.send_json(UPDATER.public())
        else:
            self.send_json({"ok": False, "error": "No encontrado."}, 404)

    def _stream(self, who: str) -> None:
        """Eventos en tiempo real (la conexión se queda abierta)."""
        global LAST_PING
        sid, q = BUS.subscribe(who)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15)
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": sigo aqui\n\n")
                self.wfile.flush()
                LAST_PING = time.time()
        except (ConnectionError, OSError):
            pass
        finally:
            BUS.unsubscribe(sid)

    def _send_bytes(self, target: Path, ctype: str) -> None:
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sound(self, name: str) -> None:
        target = SOUNDS_DIR / Path(name).name
        if not target.is_file() or target.suffix.lower() not in SOUND_EXTS:
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- POST ----------
    def do_POST(self) -> None:  # noqa: N802
        global CONFIG
        if not self._local_request() or not self._same_origin_post():
            self.send_error(403)
            return
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json({"ok": False, "error": "Solicitud inválida."}, 400)
            return
        path = urlsplit(self.path).path
        if path == "/api/settings":
            CONFIG = clean_config(data)
            save_config(CONFIG)
            BUS.emit(new_event("config", overlay=overlay_payload()))
            self.send_json({"ok": True, "config": CONFIG})
        elif path == "/api/connect":
            username = _text(data.get("username"), CONFIG["username"], 60).strip().lstrip("@")
            try:
                CONFIG["username"] = username
                save_config(CONFIG)
                LIVE.connect(username, CONFIG.get("euler_key") or "")
                self.send_json({"ok": True, "live": LIVE.public(CONFIG["top"]["count"])})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/disconnect":
            threading.Thread(target=LIVE.disconnect, daemon=True).start()
            self.send_json({"ok": True})
        elif path == "/api/test":
            event = test_event(str(data.get("type") or "gift"), str(data.get("gift") or ""))
            LIVE.push(event)
            self.send_json({"ok": True, "event": event})
        elif path == "/api/reset-stats":
            LIVE.stats.reset()
            BUS.emit(new_event("stats_reset"))
            self.send_json({"ok": True, "live": LIVE.public(CONFIG["top"]["count"])})
        elif path == "/api/anim/play":
            file = Path(str(data.get("file") or "")).name
            if not anim_path(file):
                self.send_json({"ok": False, "error": "No encontré esa animación."}, 404)
                return
            a = CONFIG["anims"]
            BUS.emit(anim_event(file, float(_num(data.get("seconds"), a["quick_seconds"], 1, 30)),
                                int(_num(data.get("size"), a["quick_size"], 10, 100)), _text(data.get("label"), "", 30), manual=True))
            self.send_json({"ok": True})
        elif path == "/api/brb":
            BRB["on"] = bool(data.get("on"))
            BUS.emit(new_event("brb", brb={**CONFIG["anims"]["brb"], **BRB}))
            self.send_json({"ok": True, "brb": BRB})
        elif path == "/api/anims/open":
            open_in_explorer(ANIM_USER)
            self.send_json({"ok": True})
        elif path == "/api/sound/pick":
            chosen = pick_sound()
            if not chosen:
                self.send_json({"ok": True, "sound": None})
                return
            try:
                self.send_json({"ok": True, "sound": import_sound(Path(chosen))})
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/sounds/open":
            open_in_explorer(SOUNDS_DIR)
            self.send_json({"ok": True})
        elif path == "/api/update/check":
            UPDATER.check(force=True)
            self.send_json({"ok": True})
        elif path == "/api/update/install":
            try:
                UPDATER.install()
                self.send_json({"ok": True})
            except RuntimeError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        else:
            self.send_json({"ok": False, "error": "No encontrado."}, 404)


from ectok_update import Updater  # noqa: E402

UPDATER = Updater(app="EC-Tok", repo="EC-Tok", tag_prefix="v", current=APP_VERSION, folder=HOME / "updates", log=log,
                  busy=lambda: "Estás conectado a un live: desconéctate primero." if LIVE.state == "live" else "")


def _idle_watch(server: ThreadingHTTPServer) -> None:
    """Cerrar si ya no hay ventana, overlays ni live conectado."""
    while True:
        time.sleep(20)
        if LIVE.want or BUS.count() > 0:
            continue
        if time.time() - LAST_PING > IDLE_EXIT_SECONDS:
            log("Sin ventana, overlays ni live: EC-Tok se cierra.")
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


def main() -> int:
    parser = argparse.ArgumentParser(description=f"EC-Tok {APP_VERSION}")
    parser.add_argument("--port", type=int, help=f"puerto (por defecto {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="no abrir la ventana")
    parser.add_argument("--stay", action="store_true", help="no cerrarse al cerrar la ventana")
    parser.add_argument("--version", action="version", version=f"EC-Tok {APP_VERSION} {BUILD_DATE}".strip())
    args = parser.parse_args()

    port = args.port or DEFAULT_PORT
    url = f"http://127.0.0.1:{port}/"
    handler = type("EcTokHandler", (Handler,), {"port": port})
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        if not args.no_browser:
            open_app_window(url)  # ya estaba abierto: solo mostrar la ventana
        return 0
    server.daemon_threads = True
    log(f"EC-Tok {APP_VERSION} ({BUILD_DATE or 'desarrollo'}) en {url}")
    with contextlib.suppress(OSError):
        ANIM_USER.mkdir(parents=True, exist_ok=True)
        readme = ANIM_USER / "LEEME.txt"
        if not readme.exists():
            readme.write_text(
                "Pon aquí tus animaciones y aparecerán en EC-Tok (pestaña Animaciones → «Actualizar lista»).\n\n"
                "Formatos: WebM con transparencia o WebP animado (se ven mejor), APNG o GIF.\n"
                "Ojo: el GIF solo tiene transparencia de «todo o nada», así que las orillas se ven serruchadas.\n"
                "Si una tuya se llama igual que una de EC-Tok, se usa la tuya.\n", encoding="utf-8")
    if not args.stay:
        threading.Thread(target=_idle_watch, args=(server,), daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.6, open_app_window, args=(url,)).start()
    if CONFIG.get("autoconnect") and CONFIG.get("username"):
        threading.Timer(1.5, lambda: LIVE.connect(CONFIG["username"], CONFIG.get("euler_key") or "")).start()
    threading.Timer(8, UPDATER.check).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        LIVE.want = False
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
