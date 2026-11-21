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
import copy
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

APP_VERSION = "2.7.2"

try:  # lo genera windows/build.ps1
    from ectok_build import BUILD_DATE  # type: ignore[import-not-found]
except ImportError:
    BUILD_DATE = ""

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
WEB_ROOT = ROOT / "web"
DEFAULT_PORT = 8795
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
# Nombres con dominio que apuntan a esta misma PC, para programas que no aceptan
# «localhost» ni «127.0.0.1» (TikTok LIVE Studio). Solo sirven los overlays.
OVERLAY_HOSTS = {"ectok.localhost", "localtest.me", "ectok.localtest.me", "127.0.0.1.nip.io"}
OVERLAY_PATHS = ("/overlay", "/overlay.html", "/api/overlay", "/api/stream")
OVERLAY_PREFIXES = ("/img/", "/anim/", "/sound/", "/metas/", "/mis-metas/")
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
SOUND_BANK = WEB_ROOT / "sonidos"  # sonidos de fábrica (CC0), ver tools/make_sounds.py
ANIM_USER = HOME / "animaciones"     # las tuyas (GIF, WebP, APNG o WebM con transparencia)
ANIM_DEFAULT = WEB_ROOT / "anim"     # las que trae EC-Tok
ANIM_BANK = HOME / "banco"           # el banco completo que se descarga aparte (personajes y efectos)
ANIM_EXTS = {".gif": "image/gif", ".webp": "image/webp", ".png": "image/png", ".apng": "image/apng", ".webm": "video/webm",
             ".mp4": "video/mp4"}
VIDEO_EXTS = (".webm", ".mp4")
IMPORT_EXTS = {*ANIM_EXTS, ".mov", ".mkv", ".avi", ".m4v", ".jpg", ".jpeg"}  # al subir se convierten a algo que el overlay maneje bien
SPECIAL_MAX = 10


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
        # banner = el cartelito de siempre; anim = además (o en su lugar) una animación del banco con el mismo texto
        "gift": {"on": True, "min_diamonds": 1, "text": "{user} envió {count}× {gift}", "seconds": 6,
                 "banner": True, "anim": False, "anim_file": "", "anim_size": 70},
        "follow": {"on": True, "text": "{user} te empezó a seguir", "seconds": 4,
                   "banner": True, "anim": False, "anim_file": "", "anim_size": 70},
        "share": {"on": True, "text": "{user} compartió el live", "seconds": 4,
                  "banner": True, "anim": False, "anim_file": "", "anim_size": 70},
        "like": {"on": False, "every": 1000, "text": "¡Ya llevamos {likes} likes!", "seconds": 4,
                 "banner": True, "anim": False, "anim_file": "", "anim_size": 70},
    },
    # Consola de sonidos para tocar a mano durante el live (ventana flotante)
    "console": {"sounds": [], "ontop": True},
    "keys_for_all": False,
    "console_seeded": False,
    "console_6x6": False,
    "style": {"color": "#FE2C55", "accent": "#25F4EE", "font_size": 34, "animation": "pop", "position": "top"},
    "sounds": [],  # [{id, on, trigger: any_gift|gift|min_diamonds|follow|share|likes, gift, min_diamonds, every, file, name, volume}]
    "sound_overlap": False,
    "tts": {"on": False, "comments": True, "gifts": True, "follows": False, "shares": False, "voice": "",
            "rate": 1.0, "volume": 1.0, "pitch": 1.0, "max_chars": 120, "skip_links": True, "prefix": "",
            "comment_text": "{user} dice: {text}", "gift_text": "{user} envió {count} {gift}. ¡Gracias!",
            "follow_text": "Gracias por seguirme, {user}", "share_text": "Gracias por compartir, {user}"},
    "goals": [{"id": "likes", "on": True, "kind": "likes", "target": 10000, "title": "Meta de likes"}],
    "top": {"count": 5, "title": "Top donadores"},
    "likers": {"count": 5, "title": "Top likes"},
    # Metas de acción: lista fija (hasta 10) de imagen + texto, ej. «🌌 Baile con canto»
    "actions": {"title": "", "layout": "side", "size": 100, "circle": False, "items": [],
                # colores: vacío = el de siempre (título en el color de acento, texto blanco con sombra)
                "title_color": "", "title_outline": "", "text_color": "", "text_outline": ""},
    "likes_rule_added": True,
    "user_likes_migrated": True,
    # Cosas que se hacen una sola vez (tienen que estar aquí para que se guarden entre reinicios).
    "battle_defaults": False,
    "custom_bank_defaults": False,
    "bank_dismissed": 0,  # «Ahora no» en la invitación a bajar el banco: hasta qué versión ya no se avisa
    "anims": {
        # trigger: any_gift | gift | min_diamonds | follow | share | likes | subscribe | superfan | envelope |
        #          battle_start | battle_end | booster
        "rules": [
            {"id": "heartme", "on": True, "trigger": "gift", "gift": "Heart Me", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "globo-corazon.webp", "seconds": 2, "name": True, "size": 80},
            {"id": "follow", "on": True, "trigger": "follow", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "escena-chico.webp", "seconds": 5, "name": True, "size": 70, "text": ""},
            {"id": "big", "on": True, "trigger": "min_diamonds", "gift": "", "min_diamonds": 1000, "every": 1000, "multiplier": 0,
             "file": "fuegos-artificiales.webp", "seconds": 5, "name": True, "size": 90},
            {"id": "chest", "on": True, "trigger": "envelope", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "confeti.webp", "seconds": 4, "name": True, "size": 90},
            {"id": "sub", "on": True, "trigger": "subscribe", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "estrellas.webp", "seconds": 4, "name": True, "size": 80},
            {"id": "likes", "on": True, "trigger": "user_likes", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 0,
             "file": "escena-chica.webp", "seconds": 5, "name": True, "size": 70, "text": ""},
            {"id": "x2", "on": True, "trigger": "booster", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 2,
             "file": "x2.webp", "seconds": 4, "name": False, "size": 70},
            {"id": "x3", "on": True, "trigger": "booster", "gift": "", "min_diamonds": 1, "every": 1000, "multiplier": 3,
             "file": "x3.webp", "seconds": 4, "name": False, "size": 70},
        ],
        # Botones de acceso rápido con texto: el texto sale en el letrero del personaje (o como alerta si no hay personaje).
        "custom": [
            {"id": "c1", "text": "¡Gracias!", "file": "escena-chica.webp", "char": True, "key": "1"},
            {"id": "c2", "text": "¡Bienvenidos!", "file": "escena-chico.webp", "char": True, "key": "2"},
            {"id": "c3", "text": "¡Síganme!", "file": "escena-chica.webp", "char": True, "key": "3"},
            {"id": "c4", "text": "¡Compartan el live!", "file": "escena-chico.webp", "char": True, "key": "4"},
            {"id": "c5", "text": "¡Toquen la pantalla!", "file": "escena-chica.webp", "char": True, "key": "5"},
        ],
        # Botones de acceso rápido normales: solo la animación (efectos, sin letrero).
        "quick": [
            {"id": "q1", "label": "Corazones", "file": "corazones.webp", "key": "6"},
            {"id": "q4", "label": "x2", "file": "x2.webp", "key": "7"},
            {"id": "q5", "label": "x3", "file": "x3.webp", "key": "8"},
            {"id": "q6", "label": "Fuegos", "file": "fuegos-artificiales.webp", "key": "9"},
        ],
        "quick_seconds": 4,
        "quick_size": 70,
        "brb": {"id": "brb", "file": "cafe-ya-regreso.webp", "text": "Ya regresamos", "sub": "No te vayas 💖", "dim": True, "key": ""},
        # Animaciones especiales: las del streamer (intro de batalla, etc.); solo se muestran cuando él las lanza.
        "special": [],
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


HOTKEY_KEYS = [*"1234567890", *(f"F{n}" for n in range(1, 13))]  # se usan con Ctrl+Alt


def _scene_files() -> set:
    """Las animaciones que son personajes con letrero (de fábrica y del banco)."""
    names: set = set()
    for folder in (ANIM_DEFAULT, ANIM_BANK):
        with contextlib.suppress(OSError, ValueError):
            data = json.loads((folder / "escenas.json").read_text(encoding="utf-8"))
            if isinstance(data, dict):
                names.update(data)
    return names


def assign_keys(a: dict) -> None:
    """Cada botón con una tecla distinta (Ctrl+Alt+tecla); los que no tienen, la siguiente libre."""
    used: set = set()
    items = [*a.get("custom", []), *a.get("quick", []), *a.get("special", []), *([a["brb"]] if isinstance(a.get("brb"), dict) else [])]
    for item in items:
        key = item.get("key") or ""
        if key not in HOTKEY_KEYS or key in used:
            item["key"] = ""
        else:
            used.add(key)
    for item in items:
        if item.get("_auto") and not item.get("key"):
            free = next((k for k in HOTKEY_KEYS if k not in used), "")
            item["key"] = free
            if free:
                used.add(free)
        item.pop("_auto", None)


def _split_quick(cfg: dict, saved: dict) -> None:
    """2.3.0: los botones rápidos se separan en Personalizados (personaje con letrero) y normales. No se borra ninguno."""
    a = cfg["anims"]
    old_quick = (saved.get("anims") or {}).get("quick")
    if not isinstance(old_quick, list):
        return  # nunca guardó botones: se quedan los de fábrica
    scenes = _scene_files()
    custom, quick = [], []
    for q in old_quick:
        if not isinstance(q, dict):
            continue
        if q.get("file") in scenes:
            custom.append({"id": str(q.get("id") or uuid.uuid4().hex[:8])[:20], "text": str(q.get("label") or "")[:60],
                           "file": q["file"], "char": True, "_auto": True})
        else:
            quick.append({**q, "_auto": True})
    for d in DEFAULT_CONFIG["anims"]["custom"]:  # completar hasta 5 personalizados con los de fábrica
        if len(custom) >= 5:
            break
        texts = DEFAULT_LIST_TEXTS.get(("custom", d["id"], "text"), {})
        custom.append({**d, "id": d["id"] if all(c["id"] != d["id"] for c in custom) else uuid.uuid4().hex[:8],
                       "text": texts.get(cfg.get("language", "es"), d["text"]), "_auto": True})
    for item in [*custom, *quick]:
        item["key"] = ""
    a["custom"], a["quick"] = custom, quick
    assign_keys(a)


def load_config() -> dict:
    with contextlib.suppress(OSError, json.JSONDecodeError):
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            cfg = _merge(DEFAULT_CONFIG, saved)
            for rule in cfg["anims"]["rules"]:  # 1.1.2: el Heart Me de fábrica ahora es el globo corazón
                if rule.get("id") == "heartme" and rule.get("file") == "corazones.webp":
                    rule.update(file="globo-corazon.webp", seconds=2, size=80)
            if not saved.get("likes_rule_added"):  # 1.5.3: animación de fábrica cada 1000 likes
                cfg["likes_rule_added"] = True
                if not any(r.get("trigger") in ("likes", "user_likes") for r in cfg["anims"]["rules"]):
                    cfg["anims"]["rules"].append({"id": "likes", "on": True, "trigger": "user_likes", "gift": "", "min_diamonds": 1,
                                                  "every": 1000, "multiplier": 0, "file": "escena-chica.webp", "seconds": 5,
                                                  "name": True, "size": 70, "text": ""})
            for rule in cfg["anims"]["rules"]:
                # 1.6.0: la regla de likes de fábrica (1.5.3) ahora cuenta los likes de cada persona
                if (rule.get("id") == "likes" and rule.get("trigger") == "likes" and not rule.get("text")
                        and rule.get("file") == "escena-chica.webp" and not saved.get("user_likes_migrated")):
                    rule.update(trigger="user_likes", name=True)
                if "name" not in rule:  # 1.3.0: mostrar el nombre de quien lo mandó
                    rule["name"] = rule.get("id") in ("heartme", "follow", "big", "chest", "sub")
            if "custom" not in (saved.get("anims") or {}):
                _split_quick(cfg, saved)
            _keys_for_all(cfg, saved)
            _seed_console(cfg, saved)
            return cfg
    cfg = _merge(DEFAULT_CONFIG, {})
    _keys_for_all(cfg, {})
    _seed_console(cfg, {})
    return cfg


def _seed_console(cfg: dict, saved: dict) -> None:
    """2.6.0: la consola de sonidos viene con los 36 recomendados (6×6) del banco (una sola vez; si luego los quitas, no regresan solos)."""
    if saved.get("console_seeded"):
        # 2.6.1: quien recibió en 2.6.0 los 63 sonidos y no los tocó, pasa a los 36 recomendados (6×6)
        if not saved.get("console_6x6"):
            cfg["console_6x6"] = True
            bank: list = []
            with contextlib.suppress(OSError, ValueError):
                bank = json.loads((SOUND_BANK / "sonidos.json").read_text(encoding="utf-8"))
            files = [x.get("file") for x in cfg["console"]["sounds"]]
            if bank and len(files) == len(bank) and set(files) == {b["file"] for b in bank}:
                cfg["console"]["sounds"] = bank_console_items(cfg.get("language", "es"))
        return
    cfg["console_6x6"] = True
    cfg["console_seeded"] = True
    if not cfg["console"]["sounds"]:
        cfg["console"]["sounds"] = bank_console_items(cfg.get("language", "es"))


# La consola recomendada: 6×6 = 36 sonidos del banco, por renglones (festejo, risas, efectos, voces).
CONSOLE_RECOMMENDED = [
    "aplausos.mp3", "ovacion.mp3", "redoble-platillo.mp3", "corneta.mp3", "ta-da.mp3", "fanfarria-orquesta.mp3",
    "victoria-piano.mp3", "guitarra-rockera.mp3", "fanfarria-8bit.mp3", "fuegos-artificiales.mp3", "cañon-confeti.mp3", "jingle-alegre.mp3",
    "risa-mujer.mp3", "risa-hombre.mp3", "risa-malvada.mp3", "eructo.mp3", "boing.mp3", "triste-trombon.mp3",
    "subir-nivel.mp3", "power-up.mp3", "monedas.mp3", "magia.mp3", "campanitas.mp3", "ding.mp3",
    "subida.mp3", "whoosh.mp3", "silbato.mp3", "tambor-militar.mp3", "platillo.mp3", "laser.mp3",
    "voz-congratulations.mp3", "voz-you-win.mp3", "voz-winner.mp3", "voz-level-up.mp3", "voz-fight.mp3", "voz-game-over.mp3",
]


def bank_console_items(lang: str, skip: set | None = None) -> list[dict]:
    colors = ["#FE2C55", "#25F4EE", "#FFB020", "#7C5CFF", "#2ECC71", "#FF7AB6", "#3DA5FF", "#FF6B3D"]
    order = {"fiesta": 0, "risas": 1, "efectos": 2, "voces": 3}
    bank: list = []
    with contextlib.suppress(OSError, ValueError):  # (se usa al cargar la configuración, antes de sound_bank())
        bank = json.loads((SOUND_BANK / "sonidos.json").read_text(encoding="utf-8"))
    by_file = {b["file"]: b for b in bank}
    bank = [by_file[f] for f in CONSOLE_RECOMMENDED if f in by_file]
    items = []
    for b in bank:
        if skip and b["file"] in skip:
            continue
        name = (b.get("name") or {}).get(lang) or (b.get("name") or {}).get("es") or Path(b["file"]).stem
        items.append({"id": uuid.uuid4().hex[:8], "name": name[:40], "file": b["file"], "volume": 100,
                      "color": colors[order.get(b.get("cat"), 0) * 2 % len(colors)]})
    return items


def my_sounds() -> list[dict]:
    """Los sonidos que tú agregaste (tu carpeta de sonidos)."""
    if not SOUNDS_DIR.is_dir():
        return []
    return [{"file": p.name, "name": re.sub(r"[_]+", " ", p.stem).strip(), "cat": "tuyos", "mine": True}
            for p in sorted(SOUNDS_DIR.iterdir(), key=lambda p: p.name.lower()) if p.is_file() and p.suffix.lower() in SOUND_EXTS]


def _keys_for_all(cfg: dict, saved: dict) -> None:
    """2.5.3: las animaciones especiales y «Ya regresamos» también traen tecla Ctrl+Alt (la siguiente libre), una sola vez."""
    if saved.get("keys_for_all"):
        return
    cfg["keys_for_all"] = True
    a = cfg["anims"]
    for item in [*a.get("special", []), a["brb"]]:
        if not item.get("key"):
            item["_auto"] = True
    assign_keys(a)


def save_config(config: dict) -> None:
    with CONFIG_LOCK:
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(CONFIG_PATH)


# Textos que trae EC-Tok de fábrica, en cada idioma. Al cambiar de idioma se cambian solo los que
# no habías editado (si el texto sigue igual al de fábrica del idioma anterior).
DEFAULT_TEXTS: dict[tuple, dict[str, str]] = {
    ("alerts", "gift", "text"): {"es": "{user} envió {count}× {gift}", "en": "{user} sent {count}× {gift}", "pt": "{user} enviou {count}× {gift}"},
    ("alerts", "follow", "text"): {"es": "{user} te empezó a seguir", "en": "{user} followed you", "pt": "{user} começou a te seguir"},
    ("alerts", "share", "text"): {"es": "{user} compartió el live", "en": "{user} shared the LIVE", "pt": "{user} compartilhou a live"},
    ("alerts", "like", "text"): {"es": "¡Ya llevamos {likes} likes!", "en": "We reached {likes} likes!", "pt": "Já temos {likes} curtidas!"},
    ("tts", "comment_text"): {"es": "{user} dice: {text}", "en": "{user} says: {text}", "pt": "{user} diz: {text}"},
    ("tts", "gift_text"): {"es": "{user} envió {count} {gift}. ¡Gracias!", "en": "{user} sent {count} {gift}. Thank you!", "pt": "{user} enviou {count} {gift}. Obrigado!"},
    ("tts", "follow_text"): {"es": "Gracias por seguirme, {user}", "en": "Thanks for following, {user}", "pt": "Obrigado por me seguir, {user}"},
    ("tts", "share_text"): {"es": "Gracias por compartir, {user}", "en": "Thanks for sharing, {user}", "pt": "Obrigado por compartilhar, {user}"},
    ("top", "title"): {"es": "Top donadores", "en": "Top gifters", "pt": "Top doadores"},
    ("likers", "title"): {"es": "Top likes", "en": "Top likers", "pt": "Top curtidas"},
    ("anims", "brb", "text"): {"es": "Ya regresamos", "en": "Be right back", "pt": "Já voltamos"},
    ("anims", "brb", "sub"): {"es": "No te vayas 💖", "en": "Don't go anywhere 💖", "pt": "Não vá embora 💖"},
}
DEFAULT_LIST_TEXTS = {  # (lista, id, campo)
    ("goals", "likes", "title"): {"es": "Meta de likes", "en": "Likes goal", "pt": "Meta de curtidas"},
    ("quick", "q1", "label"): {"es": "Corazones", "en": "Hearts", "pt": "Corações"},
    ("quick", "q2", "label"): {"es": "Confeti", "en": "Confetti", "pt": "Confete"},
    ("quick", "q3", "label"): {"es": "¡Gracias!", "en": "Thank you!", "pt": "Obrigado!"},
    ("quick", "q6", "label"): {"es": "Fuegos", "en": "Fireworks", "pt": "Fogos"},
    ("custom", "c1", "text"): {"es": "¡Gracias!", "en": "Thank you!", "pt": "Obrigado!"},
    ("custom", "c2", "text"): {"es": "¡Bienvenidos!", "en": "Welcome!", "pt": "Bem-vindos!"},
    ("custom", "c3", "text"): {"es": "¡Síganme!", "en": "Follow me!", "pt": "Me sigam!"},
    ("custom", "c4", "text"): {"es": "¡Compartan el live!", "en": "Share the LIVE!", "pt": "Compartilhem a live!"},
    ("custom", "c5", "text"): {"es": "¡Toquen la pantalla!", "en": "Tap the screen!", "pt": "Toquem na tela!"},
}


def _list_for(cfg: dict, name: str) -> list:
    return cfg["goals"] if name == "goals" else cfg["anims"][name]


def set_language(cfg: dict, old: str, new: str) -> None:
    """Cambiar los textos de fábrica al nuevo idioma (los que editaste se quedan)."""
    for path, texts in DEFAULT_TEXTS.items():
        node = cfg
        for key in path[:-1]:
            node = node[key]
        if node.get(path[-1]) == texts.get(old):
            node[path[-1]] = texts[new]
    thanks = {"es": "gracias.webp", "en": "thank-you.webp", "pt": "obrigado.webp"}  # la animación con texto
    for item in [*cfg["anims"]["rules"], *cfg["anims"]["quick"]]:
        if item.get("file") == thanks.get(old):
            item["file"] = thanks[new]
    for (name, item_id, field), texts in DEFAULT_LIST_TEXTS.items():
        for item in _list_for(cfg, name):
            if item.get("id") == item_id and item.get(field) == texts.get(old):
                item[field] = texts[new]
    cfg["language"] = new


def _first_language() -> None:
    """La primera vez: el idioma que elegiste en el instalador."""
    if CONFIG_PATH.exists():
        return
    with contextlib.suppress(OSError):
        lang = (HOME / "language.txt").read_text(encoding="utf-8").strip().lower()[:2]
        if lang in ("en", "pt"):
            set_language(CONFIG, "es", lang)
            save_config(CONFIG)


CONFIG = load_config()
_first_language()
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
    if data.get("language") in ("es", "en", "pt") and data["language"] != cfg["language"]:
        new_lang = data["language"]
        data = {k: v for k, v in data.items() if k not in ("alerts", "tts", "top", "anims", "goals")}  # se cambian abajo
        set_language(cfg, cfg["language"], new_lang)
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
                for flag in ("banner", "anim"):
                    if isinstance(new.get(flag), bool):
                        current[flag] = new[flag]
                if "anim_file" in new:
                    current["anim_file"] = Path(str(new.get("anim_file") or "")).name
                current["anim_size"] = int(_num(new.get("anim_size"), current.get("anim_size", 70), 10, 100))
    console = data.get("console")
    if isinstance(console, dict):
        c = cfg["console"]
        if isinstance(console.get("ontop"), bool):
            c["ontop"] = console["ontop"]
        if isinstance(console.get("sounds"), list):
            c["sounds"] = [{"id": _text(x.get("id"), uuid.uuid4().hex[:8], 20), "name": _text(x.get("name"), "Sonido", 40),
                            "file": Path(str(x.get("file") or "")).name, "volume": int(_num(x.get("volume"), 100, 0, 100)),
                            "color": x.get("color") if HEX.fullmatch(str(x.get("color") or "")) else ""}
                           for x in console["sounds"][:CONSOLE_MAX] if isinstance(x, dict) and x.get("file")]
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
        triggers = ("any_gift", "gift", "min_diamonds", "follow", "share", "likes", "user_likes", "subscribe", "superfan", "envelope",
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
                                  "size": int(_num(r.get("size"), 70, 10, 100)), "name": bool(r.get("name")),
                                  "text": _text(r.get("text"), "", 120)})
            a["rules"] = rules
        if isinstance(anims.get("quick"), list):
            a["quick"] = [{"id": _text(q.get("id"), uuid.uuid4().hex[:8], 20), "label": _text(q.get("label"), "Animación", 30),
                           "file": Path(str(q.get("file") or "")).name, "key": _text(q.get("key"), "", 4)}
                          for q in anims["quick"][:12] if isinstance(q, dict)]
        if isinstance(anims.get("custom"), list):
            a["custom"] = [{"id": _text(q.get("id"), uuid.uuid4().hex[:8], 20), "text": _text(q.get("text"), "", 60),
                            "file": Path(str(q.get("file") or "")).name, "char": q.get("char") is not False,
                            "key": _text(q.get("key"), "", 4)} for q in anims["custom"][:12] if isinstance(q, dict)]
        a["quick_seconds"] = float(_num(anims.get("quick_seconds"), a["quick_seconds"], 1, 30))
        a["quick_size"] = int(_num(anims.get("quick_size"), a["quick_size"], 10, 100))
        if isinstance(anims.get("special"), list):
            # sound: "" = el sonido del video · "none" = sin sonido · un archivo de sonido (banco o tuyo) en lugar del del video
            a["special"] = [{"id": _text(q.get("id"), uuid.uuid4().hex[:8], 20), "label": _text(q.get("label"), "Especial", 40),
                             "file": Path(str(q.get("file") or "")).name, "size": int(_num(q.get("size"), 100, 10, 100)),
                             "volume": int(_num(q.get("volume"), 100, 0, 100)), "seconds": float(_num(q.get("seconds"), 0, 0, 120)),
                             "key": _text(q.get("key"), "", 4), "sound": Path(_text(q.get("sound"), "", 120)).name,
                             "_auto": "key" not in q}  # las de antes (sin tecla) toman la siguiente libre
                            for q in anims["special"][:SPECIAL_MAX] if isinstance(q, dict)]
        brb = anims.get("brb")
        if isinstance(brb, dict):
            a["brb"]["file"] = Path(str(brb.get("file") or a["brb"]["file"])).name
            a["brb"]["text"] = _text(brb.get("text"), a["brb"]["text"], 60)
            a["brb"]["sub"] = _text(brb.get("sub"), a["brb"]["sub"], 80)
            if isinstance(brb.get("dim"), bool):
                a["brb"]["dim"] = brb["dim"]
            a["brb"]["id"] = "brb"
            a["brb"]["key"] = _text(brb.get("key"), "", 4)
            if "key" not in brb:  # 2.5.3: «Ya regresamos» también trae su tecla; la siguiente libre
                a["brb"]["_auto"] = True
        assign_keys(a)
    top = data.get("top")
    if isinstance(top, dict):
        cfg["top"]["count"] = int(_num(top.get("count"), cfg["top"]["count"], 1, 10))
        cfg["top"]["title"] = _text(top.get("title"), cfg["top"]["title"], 60)
    likers = data.get("likers")
    if isinstance(likers, dict):
        cfg["likers"]["count"] = int(_num(likers.get("count"), cfg["likers"]["count"], 1, 10))
        cfg["likers"]["title"] = _text(likers.get("title"), cfg["likers"]["title"], 60)
    actions = data.get("actions")
    if isinstance(actions, dict):
        a = cfg["actions"]
        a["title"] = _text(actions.get("title"), a["title"], 60)
        if actions.get("layout") in ("side", "stack"):
            a["layout"] = actions["layout"]
        a["size"] = int(_num(actions.get("size"), a["size"], 40, 250))
        if isinstance(actions.get("circle"), bool):
            a["circle"] = actions["circle"]
        for key in ("title_color", "title_outline", "text_color", "text_outline"):
            if key in actions:
                value = str(actions.get(key) or "")
                a[key] = value.upper() if HEX.fullmatch(value) else ""
        if isinstance(actions.get("items"), list):
            items = []
            for item in actions["items"][:10]:
                if isinstance(item, dict):
                    image = str(item.get("image") or "")
                    items.append({"id": re.sub(r"[^\w-]", "", str(item.get("id") or uuid.uuid4().hex[:8]))[:12] or uuid.uuid4().hex[:8],
                                  "image": image if action_image_path(image) else "", "text": _text(item.get("text"), "", 60)})
            a["items"] = items
    return cfg


# ---------------------------------------------------------------------------
# Eventos en vivo para la ventana y los overlays (Server-Sent Events)
# ---------------------------------------------------------------------------
def _peer_closed(sock) -> bool:
    """¿La otra punta cerró la conexión? (sin esperar a que falle un envío)."""
    import select

    with contextlib.suppress(OSError, ValueError):
        ready, _w, _x = select.select([sock], [], [], 0)
        if ready:
            import socket

            return sock.recv(1, socket.MSG_PEEK) == b""
        return False
    return True


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
USER_LIKE_MARKS: dict[tuple, int] = {}
LIKE_MARKS: dict[str, int] = {}
ALERT_LIKE_MARK = {"value": None}
CONSOLE_MAX = 100


def anim_label(stem: str) -> str:
    """«Girl-Dey-Sign-Up» → «Girl Dey Sign Up»; «x2» → «X2»; «fuegos-artificiales» → «Fuegos artificiales»."""
    text = re.sub(r"[-_]+", " ", stem).strip()
    return text[:1].upper() + text[1:] if text else stem


ANIM_NAMES_FILE = "nombres.json"    # en la carpeta de tus animaciones: el nombre con que tú las llamaste
ANIM_ORIGIN_FILE = "origenes.json"  # y de qué archivo de tu PC salió cada una


def _anim_map(name: str) -> dict:
    with contextlib.suppress(OSError, ValueError):
        data = json.loads((ANIM_USER / name).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    return {}


def anim_names() -> dict:
    return _anim_map(ANIM_NAMES_FILE)


def _set_anim_map(name: str, file: str, value: str) -> None:
    data = _anim_map(name)
    if value:
        data[file] = value
    else:
        data.pop(file, None)
    ANIM_USER.mkdir(parents=True, exist_ok=True)
    (ANIM_USER / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def set_anim_name(file: str, name: str) -> None:
    _set_anim_map(ANIM_NAMES_FILE, file, re.sub(r"\s+", " ", name).strip()[:40])


def list_animations() -> list[dict]:
    found: dict[str, dict] = {}
    names, origins = anim_names(), _anim_map(ANIM_ORIGIN_FILE)
    for folder, source in ((ANIM_DEFAULT, "ec-tok"), (ANIM_BANK, "ec-tok"), (ANIM_USER, "tuya")):
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.is_file() and path.suffix.lower() in ANIM_EXTS and "-parte-" not in path.name:
                    found[path.name] = {"file": path.name, "name": (names.get(path.name) if source == "tuya" else None) or anim_label(path.stem),
                                        "source": source, "video": path.suffix.lower() in VIDEO_EXTS,
                                        "scene": path.name in SCENES, "path": str(path),
                                        "from": origins.get(path.name, "") if source == "tuya" else ""}
    return sorted(found.values(), key=lambda a: _norm(a["name"]))


def _load_scenes() -> dict:
    """Escenas: un personaje con letrero (el texto lo pone EC-Tok) y partes que se mueven aparte."""
    scenes: dict = {}
    for folder in (ANIM_DEFAULT, ANIM_BANK):
        with contextlib.suppress(OSError, ValueError):
            data = json.loads((folder / "escenas.json").read_text(encoding="utf-8"))
            if isinstance(data, dict):
                scenes.update(data)
    return scenes


SCENES = _load_scenes()

# ---------------------------------------------------------------------------
# Banco completo de animaciones: se descarga aparte (un .zip en GitHub) para que el instalador siga ligero
# ---------------------------------------------------------------------------
# En GitHub cada banco es un release «banco-N» con un ectok-banco-N.zip; «Buscar actualización» busca el N más alto.
BANK_RELEASES = "https://api.github.com/repos/cesarmugica/EC-Tok/releases?per_page=40"
BANK = {"state": "idle", "percent": 0.0, "error": "", "latest": 0, "url": "", "size": 0, "checked": False, "checked_at": 0.0}


def bank_check() -> None:
    import urllib.request

    try:
        request = urllib.request.Request(BANK_RELEASES, headers={"User-Agent": f"EC-Tok/{APP_VERSION}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            releases = json.loads(response.read())
        best = (0, "", 0)
        for rel in releases:
            tag = rel.get("tag_name") or ""
            if not tag.startswith("banco-") or rel.get("draft") or not tag[6:].isdigit():
                continue
            zipa = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")), None)
            if zipa and int(tag[6:]) > best[0]:
                best = (int(tag[6:]), zipa["browser_download_url"], int(zipa.get("size") or 0))
        BANK.update(latest=best[0], url=best[1], size=best[2], checked=True, checked_at=time.time(), error="")
    except Exception as exc:  # noqa: BLE001
        BANK.update(checked=True, checked_at=time.time(), error="No se pudo buscar el banco (¿sin internet?).")
        log(f"Banco de animaciones (buscar): {exc}")


def bank_installed() -> int:
    with contextlib.suppress(OSError, ValueError):
        return int((ANIM_BANK / "version.txt").read_text(encoding="utf-8").strip())
    return 0


def bank_status() -> dict:
    count = sum(1 for p in ANIM_BANK.glob("*") if p.suffix.lower() in ANIM_EXTS) if ANIM_BANK.is_dir() else 0
    return {**BANK, "installed": bank_installed(), "count": count, "published": bool(BANK["url"]),
            "dismissed": int(CONFIG.get("bank_dismissed") or 0)}


def _bank_download() -> None:
    import urllib.request
    import zipfile

    global SCENES
    BANK.update(state="downloading", percent=0.0, error="")
    tmp = HOME / "banco-descarga.zip"
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        if not BANK["url"]:
            bank_check()
        if not BANK["url"]:
            raise RuntimeError("todavía no hay banco publicado")
        version = BANK["latest"]
        request = urllib.request.Request(BANK["url"], headers={"User-Agent": f"EC-Tok/{APP_VERSION}"})
        with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            got = 0
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                got += len(chunk)
                BANK["percent"] = round(got * 100 / total, 1) if total else 0.0
        BANK.update(state="installing")
        new = HOME / "banco-nuevo"
        shutil.rmtree(new, ignore_errors=True)
        with zipfile.ZipFile(tmp) as zf:
            for info in zf.infolist():
                name = Path(info.filename).name  # sin carpetas (y sin «../»)
                if not name or info.is_dir() or (Path(name).suffix.lower() not in ANIM_EXTS and name not in ("escenas.json", "version.txt")):
                    continue
                new.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, (new / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        (new / "version.txt").write_text(str(version), encoding="utf-8")
        shutil.rmtree(ANIM_BANK, ignore_errors=True)
        new.replace(ANIM_BANK)
        SCENES = _load_scenes()
        bank_defaults()
        bank_custom_defaults()
        HOTKEYS.refresh()
        BANK.update(state="done", percent=100.0)
        log(f"Banco de animaciones {version} instalado")
    except Exception as exc:  # noqa: BLE001
        BANK.update(state="error", error="No se pudo descargar el banco (¿sin internet?)." if BANK["url"] else "")
        log(f"Banco de animaciones: {exc}")
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def bank_defaults() -> None:
    """Con el banco instalado: una regla para cuando empieza una batalla y un botón rápido «⚔ Batalla» (una sola vez)."""
    duel = "Duel-Boy-Viking.webm"
    if CONFIG.get("battle_defaults") or not (ANIM_BANK / duel).is_file():
        return
    with CONFIG_LOCK:
        a = CONFIG["anims"]
        if not any(r.get("trigger") == "battle_start" for r in a["rules"]):
            a["rules"].append({"id": "battle", "on": True, "trigger": "battle_start", "gift": "", "min_diamonds": 1, "every": 1000,
                               "multiplier": 0, "file": duel, "seconds": 6, "size": 80, "name": False, "text": ""})
        if len(a["quick"]) < 12 and not any(q.get("file", "").startswith("Duel-") for q in a["quick"]):
            a["quick"].append({"id": "battle", "label": "⚔ Batalla", "file": duel, "key": "", "_auto": True})
            assign_keys(a)
        CONFIG["battle_defaults"] = True
    save_config(CONFIG)


BANK_CUSTOM_CHARS = {"c1": "Girl-Dey-Sign-Up.webm", "c2": "Boy-Mat-Jumping.webm", "c3": "Pet-Mon-Sign-Up.webm",
                     "c4": "Girl-Lau-Jumping.webm", "c5": "Pet-Cat-Jumping.webm"}


def bank_custom_defaults() -> None:
    """Con el banco instalado, los personalizados de fábrica usan personajes del banco (una sola vez; los que cambiaste se quedan)."""
    if CONFIG.get("custom_bank_defaults") or not all((ANIM_BANK / f).is_file() for f in BANK_CUSTOM_CHARS.values()):
        return
    with CONFIG_LOCK:
        for item in CONFIG["anims"].get("custom", []):
            new = BANK_CUSTOM_CHARS.get(item.get("id"))
            if new and item.get("file") in ("escena-chica.webp", "escena-chico.webp"):
                item["file"] = new
        CONFIG["custom_bank_defaults"] = True
    save_config(CONFIG)


def bank_remove() -> None:
    global SCENES
    shutil.rmtree(ANIM_BANK, ignore_errors=True)
    SCENES = _load_scenes()
    BANK.update(state="idle", percent=0.0, error="")

# Texto de fábrica del letrero, según lo que pasó (cada regla puede poner el suyo).
SIGN_DEFAULTS = {
    "gift": {"es": "¡Gracias por tu {gift}, {user}!", "en": "Thanks for the {gift}, {user}!", "pt": "Obrigado pelo {gift}, {user}!"},
    "follow": {"es": "¡Gracias por seguirme, {user}!", "en": "Thanks for following, {user}!", "pt": "Obrigado por me seguir, {user}!"},
    "share": {"es": "¡Gracias por compartir, {user}!", "en": "Thanks for sharing, {user}!", "pt": "Obrigado por compartilhar, {user}!"},
    "like": {"es": "¡Ya somos {likes} likes!", "en": "We hit {likes} likes!", "pt": "Já são {likes} curtidas!"},
    "user_likes": {"es": "¡Gracias por tus {likes} likes, {user}!", "en": "Thanks for your {likes} likes, {user}!", "pt": "Obrigado pelas suas {likes} curtidas, {user}!"},
    "subscribe": {"es": "¡Gracias por suscribirte, {user}!", "en": "Thanks for subscribing, {user}!", "pt": "Obrigado por se inscrever, {user}!"},
    "superfan": {"es": "¡Gracias, súper fan {user}!", "en": "Thank you, super fan {user}!", "pt": "Obrigado, super fã {user}!"},
    "envelope": {"es": "¡Gracias por el cofre, {user}!", "en": "Thanks for the treasure chest, {user}!", "pt": "Obrigado pelo baú, {user}!"},
    "": {"es": "¡Gracias!", "en": "Thank you!", "pt": "Obrigado!"},
}
GIFT_NAMES_ES = {"heart me": "Quiéreme", "rose": "Rosa", "lion": "León", "universe": "Universo", "galaxy": "Galaxia",
                 "finger heart": "Corazón con los dedos", "ice cream cone": "Helado", "doughnut": "Dona", "perfume": "Perfume",
                 "money gun": "Pistola de dinero", "tiktok": "TikTok"}


def sign_text(template: str, ev: dict | None, show_name: bool = True) -> str:
    """El texto del letrero con los comodines llenos. {user} se deja para que el overlay lo resalte."""
    lang = CONFIG["language"]
    ev = ev or {}
    kind = ev.get("type", "")
    text = template.strip() or SIGN_DEFAULTS.get(kind if kind in SIGN_DEFAULTS else "", SIGN_DEFAULTS[""])[lang]
    gift = ev.get("gift") or {}
    gname = gift.get("name", "")
    if lang == "es":
        gname = GIFT_NAMES_ES.get(_norm(gname), gname)
    likes = ev.get("milestone") or LIVE.stats.likes
    values = {"{gift}": gname, "{count}": str(gift.get("count") or ""), "{likes}": f"{likes:,}",
              "{diamonds}": str(gift.get("total") or "")}
    for key, value in values.items():
        text = text.replace(key, value)
    if not show_name or not (ev.get("user") or {}).get("name"):
        text = re.sub(r",?\s*\{user\}", "", text).replace("{user}", "")
    return text


def anim_path(name: str) -> Path | None:
    name = Path(name).name
    for folder in (ANIM_USER, ANIM_BANK, ANIM_DEFAULT):
        target = folder / name
        if target.is_file() and target.suffix.lower() in ANIM_EXTS:
            return target
    return None


def anim_event(file: str, seconds: float, size: int, label: str = "", manual: bool = False,
               who: dict | None = None, caption: str = "", sign: str = "") -> dict:
    scene = SCENES.get(file)
    if scene:  # en las escenas el nombre va en el letrero, no en la tarjeta de abajo
        return new_event("anim", file=file, video=False, seconds=seconds, size=size, label=label, manual=manual,
                         scene=scene, sign=sign, user=(who or {}).get("name", ""))
    return new_event("anim", file=file, video=file.lower().endswith(VIDEO_EXTS), seconds=seconds, size=size,
                     label=label, manual=manual, who=who, caption=caption)


def special_event(sp: dict, preview: bool = False) -> dict:
    sound = sp.get("sound") or ""
    return new_event("special", file=sp["file"], video=sp["file"].lower().endswith(VIDEO_EXTS), size=sp["size"],
                     volume=sp["volume"], seconds=sp["seconds"], label=sp["label"], preview=bool(preview),
                     mute=sound == "none", sound=sound if sound not in ("", "none") else "")


def brb_payload() -> dict:
    # own: hay una fuente ☕ «Ya regresamos» abierta en LIVE Studio/OBS; entonces ya no sale en la de animaciones
    return {**CONFIG["anims"]["brb"], **BRB, "own": BUS.count("overlay-brb") > 0}


def set_brb(on: bool) -> None:
    BRB["on"] = bool(on)
    BUS.emit(new_event("brb", brb=brb_payload()))


def fire_button(kind: str, item_id: str, preview: bool = False) -> str:
    """Lanzar un botón de acceso rápido (clic o Ctrl+Alt+tecla). Regresa el error, o "" si salió."""
    a = CONFIG["anims"]
    if kind == "brb":  # la tecla de «Ya regresamos» lo pone y lo quita
        set_brb(not BRB["on"])
        return ""
    item = next((q for q in a.get(kind, []) if q.get("id") == item_id), None) if kind in ("custom", "quick", "special") else None
    if not item:
        return "No encontré ese botón."
    if kind == "special":
        if not anim_path(item.get("file") or ""):
            return "Esa animación especial no tiene archivo."
        BUS.emit(special_event(item, preview))
        return ""
    secs, size = a["quick_seconds"], a["quick_size"]
    if kind == "custom":
        text = (item.get("text") or "").strip()
        file = item.get("file") or ""
        if item.get("char") and file in SCENES and anim_path(file):  # el texto en el letrero del personaje
            ev = anim_event(file, secs, size, text, manual=True, sign=sign_text(text, {}, False))
        else:  # sin personaje: el texto sale como alerta
            if not text:
                return "Escribe el texto del botón."
            ev = new_event("custom", text=text, seconds=secs)
    else:
        file = item.get("file") or ""
        if not anim_path(file):
            return "Ese botón no tiene animación."
        ev = anim_event(file, secs, size, item.get("label", ""), manual=True)
    BUS.emit(ev | {"preview": bool(preview)})
    return ""


class Hotkeys:
    """Ctrl+Alt+tecla en cualquier ventana (Windows): lanza los botones de acceso rápido aunque estés en LIVE Studio."""
    MOD = 0x0002 | 0x0001 | 0x4000  # MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
    WM_HOTKEY, WM_REFRESH = 0x0312, 0x8001

    def __init__(self) -> None:
        self.thread_id = 0
        self.ids: dict[int, tuple[str, str]] = {}
        self.problems: dict[str, str] = {}  # tecla -> «ocupada» o el carácter que escribe en este teclado
        self.active = False

    @staticmethod
    def vk(key: str) -> int:
        return 0x6F + int(key[1:]) if key.startswith("F") else ord(key)

    def start(self) -> None:
        if IS_WINDOWS:
            threading.Thread(target=self._run, daemon=True, name="hotkeys").start()

    def refresh(self) -> None:
        if IS_WINDOWS and self.thread_id:
            import ctypes

            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_REFRESH, 0, 0)  # type: ignore[attr-defined]

    def _typed_char(self, user32, vk: int) -> str:
        """Lo que escribe Ctrl+Alt+tecla en este teclado (AltGr = Ctrl+Alt: en algunos teclados Ctrl+Alt+2 es «@»)."""
        import ctypes

        from ctypes import wintypes

        user32.GetKeyboardLayout.restype = ctypes.c_void_p
        user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        user32.ToUnicodeEx.restype = ctypes.c_int
        user32.ToUnicodeEx.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ubyte), wintypes.LPWSTR,
                                       ctypes.c_int, wintypes.UINT, ctypes.c_void_p]
        state = (ctypes.c_ubyte * 256)()
        state[0x11] = state[0x12] = 0x80  # VK_CONTROL y VK_MENU presionadas
        buf = ctypes.create_unicode_buffer(8)
        try:
            hkl = user32.GetKeyboardLayout(0)
            n = user32.ToUnicodeEx(vk, user32.MapVirtualKeyW(vk, 0), state, buf, 8, 0x4, hkl)  # 0x4: no cambiar el estado del teclado
        except Exception:  # noqa: BLE001
            return ""
        return buf.value[:n].strip() if n > 0 else ""

    def _register(self, user32) -> None:
        for hid in list(self.ids):
            user32.UnregisterHotKey(None, hid)
        self.ids.clear()
        self.problems = {}
        a = CONFIG["anims"]
        hid = 1
        for kind in ("custom", "quick", "special", "brb"):
            for item in ([a["brb"]] if kind == "brb" else a.get(kind, [])):
                key = item.get("key") or ""
                if key not in HOTKEY_KEYS:
                    continue
                vk = self.vk(key)
                typed = self._typed_char(user32, vk) if not key.startswith("F") else ""
                if typed:  # registrarla te dejaría sin poder escribir ese carácter
                    self.problems[key] = typed
                    continue
                if user32.RegisterHotKey(None, hid, self.MOD, vk):
                    self.ids[hid] = (kind, item["id"])
                    hid += 1
                else:
                    self.problems[key] = "ocupada"
        self.active = True

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()  # type: ignore[attr-defined]
        try:
            self._register(user32)
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self.WM_HOTKEY and msg.wParam in self.ids:
                    kind, item_id = self.ids[msg.wParam]
                    err = fire_button(kind, item_id)
                    if err:
                        log(f"Tecla rápida: {err}")
                elif msg.message == self.WM_REFRESH:
                    self._register(user32)
        except Exception as exc:  # noqa: BLE001
            log(f"Teclas rápidas: {exc}")
            self.active = False

    def status(self) -> dict:
        return {"global": self.active, "problems": self.problems}


HOTKEYS = Hotkeys()


def anim_caption(ev: dict) -> str:
    """Lo que va junto al nombre: «Heart Me ×5», etc."""
    if ev.get("type") == "gift":
        g = ev.get("gift") or {}
        count = g.get("count") or g.get("repeat") or 1
        return f"{g.get('name', '')}{f' ×{count}' if count and count > 1 else ''}"
    return ""


# Regalos que pueden llegar con su nombre en inglés o en español (según el idioma de TikTok).
GIFT_ALIASES = [
    {"heart me", "quiereme", "quiéreme"}, {"rose", "rosa"}, {"lion", "leon", "león"}, {"universe", "universo"},
    {"galaxy", "galaxia"}, {"finger heart", "corazon con los dedos", "corazón con los dedos", "corazon de dedos"},
    {"hand hearts", "corazones con las manos", "corazon con las manos"}, {"ice cream cone", "cono de helado", "helado"},
    {"doughnut", "dona", "donut"}, {"perfume"}, {"money gun", "pistola de dinero"}, {"corgi"},
    {"tiktok universe", "universo tiktok", "universo de tiktok"}, {"interstellar", "interestelar"},
]


def _norm(name: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", name.strip().lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def same_gift(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if a == b:
        return True
    return any(a in {_norm(x) for x in group} and b in {_norm(x) for x in group} for group in GIFT_ALIASES)


def anims_for(ev: dict) -> list[dict]:
    """Qué animación toca con este evento (la regla más específica gana)."""
    rules = [r for r in CONFIG["anims"]["rules"] if r["on"] and r["file"]]
    kind, chosen = ev.get("type"), []
    if kind == "gift":
        gift = ev["gift"]
        exact = [r for r in rules if r["trigger"] == "gift" and r["gift"] and same_gift(r["gift"], gift["name"])]
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
        # Likes de cada persona: «¡Gracias por tus 1000 likes!», luego 2000, 3000…
        user = ev.get("user") or {}
        key = user.get("id") or user.get("name")
        liker = LIVE.stats.likers.get(key) if key else None
        if liker:
            out = []
            for r in rules:
                if r["trigger"] == "user_likes":
                    mark = liker["likes"] // r["every"] * r["every"]
                    seen = USER_LIKE_MARKS.get((r["id"], key), 0)
                    if seen > mark:  # se reinició la cuenta (nuevo live o «empezar de cero»)
                        seen = 0
                    if mark > seen and mark > 0:
                        USER_LIKE_MARKS[(r["id"], key)] = mark
                        out.append((r, {**ev, "type": "user_likes", "milestone": mark}))
            extra = [anim_event(r["file"], r["seconds"], r["size"], manual=False,
                                who={"name": user.get("name", ""), "avatar": user.get("avatar", "")} if r.get("name") else None,
                                caption=f"❤️ {e['milestone']:,} likes" if r.get("name") else "",
                                sign=sign_text(r.get("text", ""), e, bool(r.get("name"))) if r["file"] in SCENES else "")
                     for r, e in out]
            if extra:
                return [anim_event(r["file"], r["seconds"], r["size"], manual=False) for r in chosen] + extra
    user = ev.get("user") or {}
    who = {"name": user.get("name", ""), "avatar": user.get("avatar", "")} if user.get("name") else None
    return [anim_event(r["file"], r["seconds"], r["size"], manual=False,
                       who=who if r.get("name") else None, caption=anim_caption(ev) if r.get("name") else "",
                       sign=sign_text(r.get("text", ""), ev, bool(r.get("name"))) if r["file"] in SCENES else "")
            for r in chosen]


def alert_anims(ev: dict) -> list[dict]:
    """Alertas con «🎬 Animación» marcada: la animación elegida sale con el texto de la alerta en el letrero."""
    kind = ev.get("type")
    alerts = CONFIG["alerts"]
    conf, data = None, ev
    if kind == "gift" and (ev.get("gift") or {}).get("total", 0) >= alerts["gift"].get("min_diamonds", 1):
        conf = alerts["gift"]
    elif kind in ("follow", "share"):
        conf = alerts[kind]
    elif kind == "like":
        a = alerts["like"]
        if a.get("on") and a.get("anim") and a.get("every"):
            likes = LIVE.stats.likes
            mark = likes // a["every"] * a["every"]
            if ALERT_LIKE_MARK["value"] is None or mark < ALERT_LIKE_MARK["value"]:
                ALERT_LIKE_MARK["value"] = mark  # empezar a contar desde donde va el live
            elif mark > ALERT_LIKE_MARK["value"]:
                ALERT_LIKE_MARK["value"] = mark
                conf, data = a, {"type": "like", "milestone": mark}
    if not conf or not conf.get("on") or not conf.get("anim") or not conf.get("anim_file") or not anim_path(conf["anim_file"]):
        return []
    file = conf["anim_file"]
    user = data.get("user") or {}
    who = {"name": user.get("name", ""), "avatar": user.get("avatar", "")} if user.get("name") else None
    text = sign_text(conf.get("text", ""), data, True)
    if file in SCENES:
        return [anim_event(file, conf.get("seconds", 5), conf.get("anim_size", 70), who=who, sign=text)]
    return [anim_event(file, conf.get("seconds", 5), conf.get("anim_size", 70), who=who, caption=re.sub(r"\{user\}\s*", "", text).strip())]


def live_emit(event: dict) -> None:
    BUS.emit(event)
    if event.get("type") in ("gift", "follow", "share", "like", "subscribe", "superfan", "envelope", "battle", "booster"):
        for anim in anims_for(event) + alert_anims(event):
            BUS.emit(anim)


LIVE = Live(emit=live_emit, log=log)
import ectok_live  # noqa: E402


# ---------------------------------------------------------------------------
# 🧪 Entorno de prueba: simular un live lleno (likes, follows, regalos…) para ver cómo se porta todo
# ---------------------------------------------------------------------------
SIM_KINDS = ("like", "follow", "share", "comment", "gift")
SIM_LIKER = {"id": "sim_likes", "name": "Fan de prueba", "avatar": ""}


class Simulator:
    """Manda eventos de prueba en su propio hilo, cada N segundos, por el mismo camino que los del live real
    (reglas, alertas, sonidos, metas y top). Al terminar puede dejar los números del live como estaban."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.items: list[dict] = []
        self.until = 0.0
        self.started = 0.0
        self.sent: dict[str, int] = {}
        self.snapshot: dict | None = None
        self.gen = 0

    @staticmethod
    def clean(raw) -> list[dict]:
        items = []
        for x in (raw or [])[:20]:
            if not isinstance(x, dict) or x.get("kind") not in SIM_KINDS:
                continue
            items.append({"kind": x["kind"], "count": int(_num(x.get("count"), 1, 1, 5000)),
                          "every": float(_num(x.get("every"), 10, 0.5, 3600)), "gift": _text(x.get("gift"), "", 60).strip(),
                          "min": int(_num(x.get("min"), 0, 0, 1_000_000))})
        return items

    def _snap(self) -> dict:
        st = LIVE.stats
        with st.lock:
            return copy.deepcopy({k: getattr(st, k) for k in ("started", "likes", "diamonds", "follows", "shares", "gifts",
                                                               "comments", "donors", "likers", "gift_names")})

    def start(self, items: list[dict], minutes: float) -> None:
        with self.lock:
            if not self.running:
                self.snapshot = self._snap()  # cómo estaban los números antes de la prueba
            self.gen += 1
            self.items, self.running = items, True
            self.started = time.time()
            self.until = self.started + minutes * 60
            self.sent = {}
            gen = self.gen
        threading.Thread(target=self._run, args=(gen,), daemon=True).start()
        log(f"Entorno de prueba: simulación por {minutes:g} min ({len(items)} tipos de evento)")

    def stop(self, restore: bool, finish: bool = True) -> None:
        """finish=False: solo parar (se guarda la foto de los números para preguntar después si se regresan)."""
        with self.lock:
            self.running = False
            self.gen += 1
            if not finish:
                return
            snap, self.snapshot = self.snapshot, None
        if restore and snap:
            st = LIVE.stats
            with st.lock:
                for k, v in snap.items():
                    setattr(st, k, v)
            USER_LIKE_MARKS.clear()
            LIKE_MARKS.clear()
            ALERT_LIKE_MARK["value"] = None
            BUS.emit(new_event("stats_reset"))  # los overlays de metas y top vuelven a leer los números

    def public(self) -> dict:
        with self.lock:
            return {"running": self.running, "left": max(0, round(self.until - time.time())) if self.running else 0,
                    "sent": dict(self.sent), "changed": self.snapshot is not None}

    def _event(self, item: dict) -> list[dict]:
        kind, n = item["kind"], item["count"]
        if kind == "like":  # de un solo usuario: así también cuentan las reglas «cada N likes de una persona»
            return [new_event("like", user=dict(SIM_LIKER), count=n, total_likes=0, test=True, sim=True)]
        out = []
        for _ in range(min(n, 200)):
            if kind == "gift":
                ev = test_event("gift", item["gift"])
                gift = ev["gift"]
                if item["gift"] and gift["name"].lower() != item["gift"].lower():  # un regalo que no está en la lista de prueba
                    gift.update(name=item["gift"], diamonds=max(1, item["min"]), count=1)
                elif not item["gift"] and item["min"]:  # «un regalo de N 💎 o más»
                    known = sorted((g for g in ectok_live.TEST_GIFTS if g[1] >= item["min"]), key=lambda g: g[1])
                    name, each = known[0] if known else (f"Regalo {item['min']} 💎", item["min"])
                    gift.update(name=name, diamonds=each, count=1)
                gift["total"] = gift["diamonds"] * gift["count"]
            else:
                ev = test_event(kind)
            ev["sim"] = True
            out.append(ev)
        return out

    def _run(self, gen: int) -> None:
        due = [time.time() + 0.3 + i * 0.15 for i in range(len(self.items))]
        while True:
            with self.lock:
                if gen != self.gen or not self.running:
                    return
                if time.time() >= self.until:
                    self.running = False
                    log("Entorno de prueba: terminó el tiempo de la simulación")
                    BUS.emit(new_event("sim", running=False))
                    return
                items = list(self.items)
            now = time.time()
            for i, item in enumerate(items):
                if now >= due[i]:
                    due[i] = now + item["every"]
                    for ev in self._event(item):
                        LIVE.push(ev)
                    with self.lock:
                        self.sent[item["kind"]] = self.sent.get(item["kind"], 0) + item["count"]
            time.sleep(0.1)


SIM = Simulator()

ectok_live.LANG["value"] = CONFIG["language"]


def overlay_actions() -> dict:
    a = CONFIG["actions"]
    return {**a, "items": [{**i, "url": action_image_url(i["image"])} for i in a["items"]]}


def overlay_payload() -> dict:
    """Lo que necesitan los overlays: estilos, alertas, metas y el estado del live."""
    return {"style": CONFIG["style"], "alerts": CONFIG["alerts"], "goals": CONFIG["goals"], "top": CONFIG["top"], "likers": CONFIG["likers"],
            "actions": overlay_actions(), "stats": LIVE.stats.public(CONFIG["top"]["count"]), "brb": brb_payload(),
            "lang": CONFIG["language"], "version": APP_VERSION}


def aliases_payload() -> list[list[str]]:
    return [sorted(group) for group in GIFT_ALIASES]


# ---------------------------------------------------------------------------
# Sonidos (se copian a %LOCALAPPDATA%\EC-Tok\sounds para que no se pierdan)
# ---------------------------------------------------------------------------
SOUND_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".flac", ".webm"}
PICK_LOCK = threading.Lock()


# ---------- imágenes de las metas de acción ----------
ACTION_BANK = WEB_ROOT / "metas"          # banco de fábrica (imágenes propias de EC-Tok, en HD)
ACTION_USER = HOME / "metas"              # las que sube cada quien
ACTION_EXTS = {".png", ".webp", ".jpg", ".jpeg", ".gif"}


def action_image_path(image_id: str) -> Path | None:
    kind, _, name = str(image_id).partition("/")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    folder = {"b": ACTION_BANK, "u": ACTION_USER}.get(kind)
    path = folder / name if folder else None
    return path if path and path.is_file() and path.suffix.lower() in ACTION_EXTS else None


def action_image_url(image_id: str) -> str:
    kind, _, name = str(image_id).partition("/")
    if not action_image_path(image_id):
        return ""
    return ("/metas/" if kind == "b" else "/mis-metas/") + name.replace("%", "%25").replace(" ", "%20").replace("#", "%23")


def action_images() -> dict:
    names = {}
    with contextlib.suppress(OSError, ValueError):
        names = json.loads((ACTION_BANK / "metas.json").read_text(encoding="utf-8"))
    lang = CONFIG.get("language") or "es"
    bank = []
    if ACTION_BANK.is_dir():
        for p in sorted(ACTION_BANK.iterdir()):
            if p.suffix.lower() in ACTION_EXTS:
                n = names.get(p.stem) or {}
                bank.append({"id": f"b/{p.name}", "name": n.get(lang) or n.get("es") or anim_label(p.stem), "url": action_image_url(f"b/{p.name}")})
    mine = []
    if ACTION_USER.is_dir():
        for p in sorted(ACTION_USER.iterdir(), key=lambda x: x.name.lower()):
            if p.suffix.lower() in ACTION_EXTS:
                mine.append({"id": f"u/{p.name}", "name": p.stem, "url": action_image_url(f"u/{p.name}")})
    return {"bank": bank, "mine": mine}


def import_action_image(path: Path) -> str:
    """Traer una imagen del streamer (se guarda en PNG de máximo 512 px; las GIF/WebP se quedan como vienen)."""
    ext = path.suffix.lower()
    if ext not in ACTION_EXTS:
        raise ValueError("Esa imagen no es compatible (PNG, WebP, JPG o GIF).")
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError("La imagen pesa más de 30 MB.")
    ACTION_USER.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-. ()]+", "_", path.stem)[:60].strip() or "imagen"
    keep = ext in (".gif", ".webp")
    out_ext = ext if keep else ".png"
    target = ACTION_USER / f"{safe}{out_ext}"
    n = 2
    while target.exists():
        target = ACTION_USER / f"{safe} ({n}){out_ext}"
        n += 1
    if keep or not FFMPEG:
        shutil.copy2(path, target)
    else:
        result = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(path), "-frames:v", "1",
                                 "-vf", "scale='min(512,iw)':'min(512,ih)':force_original_aspect_ratio=decrease", str(target)],
                                capture_output=True, creationflags=_no_window_flags())
        if result.returncode != 0 or not target.exists():
            shutil.copy2(path, target.with_suffix(ext))
            target = target.with_suffix(ext)
    return f"u/{target.name}"


def pick_sound() -> str | None:
    return (_pick_file({"en": "Choose the sound", "pt": "Escolha o som"}.get(CONFIG["language"], "Elige el sonido"),
                      {"en": "Sounds", "pt": "Sons"}.get(CONFIG["language"], "Sonidos"), SOUND_EXTS, Path.home() / "Music") or [None])[0]


def find_ffmpeg() -> str | None:
    """FFmpeg viene con el instalador (carpeta bin junto a ectok.exe)."""
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    name = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"
    for candidate in (exe_dir / "bin" / name, exe_dir / name):
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffmpeg")


FFMPEG = find_ffmpeg()


def _probe(path: Path) -> dict:
    """Lo básico del archivo (FFmpeg lo dice al abrirlo): tamaño, códec, si trae transparencia y audio."""
    info = {"w": 0, "h": 0, "codec": "", "alpha": False, "audio": False, "fps": 0.0}
    if not FFMPEG:
        return info
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", creationflags=_no_window_flags(), timeout=60).stderr
    video = re.search(r"Stream #\S+.*?Video: (\w+)([^\n]*)", out)
    if video:
        info["codec"] = video.group(1)
        size = re.search(r", (\d{2,5})x(\d{2,5})", video.group(2))
        if size:
            info["w"], info["h"] = int(size.group(1)), int(size.group(2))
        fps = re.search(r"([\d.]+) fps", video.group(2))
        info["fps"] = float(fps.group(1)) if fps else 0.0
        info["alpha"] = "yuva" in video.group(2) or "rgba" in video.group(2) or "pal8" in video.group(2)
    info["alpha"] = info["alpha"] or bool(re.search(r"alpha_mode\s*:\s*1", out, re.I))
    info["audio"] = "Audio:" in out
    return info


def _fit(w: int, h: int, long_side: int = 1920, short_side: int = 1080) -> str:
    """Filtro de escala para que no pase de 1920×1080 (o 1080×1920 en vertical), sin agrandar."""
    if w >= h:
        return f"scale='min({long_side},iw)':'min({short_side},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
    return f"scale='min({short_side},iw)':'min({long_side},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"


def convert_anim(src: Path, target_dir: Path, stem: str) -> Path:
    """Dejar la animación del streamer en el formato que ya usa EC-Tok:
    - video normal → MP4 H.264 (máx. 1920×1080 o 1080×1920, 30 fps), con su sonido;
    - video con transparencia → WebM VP9 con transparencia;
    - GIF/APNG → WebP animado (mismo look, mucho más ligero);
    - imagen fija grande → PNG/WebP más chica.
    Si ya viene bien (MP4 H.264 o WebM chico, WebP), se copia tal cual."""
    ext = src.suffix.lower()
    info = _probe(src)
    big = max(info["w"], info["h"]) > 1920 or min(info["w"], info["h"]) > 1080
    heavy = src.stat().st_size > 60 * 1024 * 1024
    if ext == ".webp" or not FFMPEG:
        return _copy_unique(src, target_dir, stem, ext)
    if ext == ".mp4" and info["codec"] == "h264" and not big and not heavy and info["fps"] <= 61:
        return _copy_unique(src, target_dir, stem, ext)
    if ext == ".webm" and not big and not heavy:
        return _copy_unique(src, target_dir, stem, ext)
    vf = _fit(info["w"] or 1080, info["h"] or 1920)
    if ext in (".gif", ".apng") or (ext == ".png" and info["codec"] == "apng"):
        out, args = ".webp", ["-vf", f"{vf},fps='min(25,source_fps)'", "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "82",
                              "-loop", "0", "-an"]
    elif ext in (".png", ".jpg", ".jpeg"):
        out, args = ".png", ["-vf", vf, "-frames:v", "1"]
    elif info["alpha"]:
        out, args = ".webm", ["-vf", f"{vf},fps='min(30,source_fps)'", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0",
                              "-crf", "32", "-deadline", "realtime", "-cpu-used", "8", "-c:a", "libopus", "-b:a", "128k"]
    else:
        out, args = ".mp4", ["-vf", f"{vf},fps='min(30,source_fps)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    target = _unique(target_dir, stem, out)
    tmp = target.with_name(target.stem + ".tmp" + out)
    dec = ["-c:v", "libvpx-vp9"] if ext == ".webm" and info["alpha"] and info["codec"] == "vp9" else \
          ["-c:v", "libvpx"] if ext == ".webm" and info["alpha"] else []
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *dec, "-i", str(src), *args, str(tmp)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            creationflags=_no_window_flags(), timeout=1800)
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        log(f"Convertir animación: {result.stderr.strip()[-400:]}")
        raise ValueError("No pude convertir esa animación. Prueba con otro archivo (MP4, WebM, GIF o WebP).")
    tmp.replace(target)
    return target


def _unique(folder: Path, stem: str, ext: str) -> Path:
    target, n = folder / f"{stem}{ext}", 2
    while target.exists():
        target = folder / f"{stem} ({n}){ext}"
        n += 1
    return target


def _copy_unique(src: Path, folder: Path, stem: str, ext: str) -> Path:
    same = folder / f"{stem}{ext}"
    if same.exists() and same.stat().st_size == src.stat().st_size:
        return same
    target = _unique(folder, stem, ext)
    shutil.copy2(src, target)
    return target


def pick_anim(multi: bool = False) -> list[str]:
    return _pick_file({"en": "Choose your animation", "pt": "Escolha sua animação"}.get(CONFIG["language"], "Elige tu animación"),
                      {"en": "Animations and videos", "pt": "Animações e vídeos"}.get(CONFIG["language"], "Animaciones y videos"),
                      IMPORT_EXTS, Path.home() / "Videos", multi=multi) or []


def _pick_file(title: str, kind: str, exts, folder: Path, multi: bool = False) -> list[str]:
    if not IS_WINDOWS:
        return []
    patterns = ";".join("*" + ext for ext in sorted(exts))
    q = lambda text: str(text).replace(chr(39), chr(39) * 2)  # noqa: E731
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0; StartPosition='CenterScreen'}; $owner.Show(); $owner.Activate();"
        "$d = New-Object System.Windows.Forms.OpenFileDialog;"
        f"$d.Title = '{q(title)}';"
        f"$d.Filter = '{q(kind)}|{patterns}|*.*|*.*';"
        f"$d.InitialDirectory = '{q(folder)}';"
        f"$d.Multiselect = ${'true' if multi else 'false'};"
        "if ($d.ShowDialog($owner) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.FileNames }"
    )
    with PICK_LOCK:
        result = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=_no_window_flags(), timeout=600)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def import_anim(path: Path) -> str:
    """Traer una animación o video del streamer a su carpeta de animaciones, ya convertida."""
    ext = path.suffix.lower()
    if ext not in IMPORT_EXTS:
        raise ValueError("Ese archivo no es una animación compatible (GIF, WebP, PNG, WebM, MP4).")
    if path.stat().st_size > 500 * 1024 * 1024:
        raise ValueError("La animación pesa más de 500 MB; usa una más corta o más ligera.")
    ANIM_USER.mkdir(parents=True, exist_ok=True)
    if path.parent.resolve() == ANIM_USER.resolve() and ext in ANIM_EXTS:
        return path.name
    safe = re.sub(r"[^\w\-. ()]+", "_", path.stem)[:60].replace("-parte-", "-").strip() or "animacion"
    return convert_anim(path, ANIM_USER, safe).name


PICKED: dict[str, list[str]] = {}  # archivos elegidos en el explorador, esperando convertirse


def sound_bank() -> list[dict]:
    with contextlib.suppress(OSError, ValueError):
        return json.loads((SOUND_BANK / "sonidos.json").read_text(encoding="utf-8"))
    return []


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


def open_app_window(url: str, size: str = "1180,860") -> None:
    browser = _app_browser()
    if browser:
        with contextlib.suppress(OSError):
            # Sin «autoplay policy»: la ventana tiene que poder sonar alertas y leer el chat sin que des clic.
            subprocess.Popen([browser, f"--app={url}", f"--window-size={size}",
                              "--autoplay-policy=no-user-gesture-required"], close_fds=True)
            return
    webbrowser.open(url)


CONSOLE_TITLE = "🎛 EC-Tok"  # la consola siempre se titula así (en cualquier idioma)


def set_topmost(title_prefix: str, on: bool) -> int:
    """Poner (o quitar) «siempre encima» a las ventanas cuyo título empieza así. Solo Windows."""
    if not IS_WINDOWS:
        return 0
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    # Tipos explícitos: sin ellos, en Windows de 64 bits HWND_TOPMOST (-1) y los HWND grandes no llegaban bien
    # y la ventana nunca quedaba «siempre encima».
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    found: list = []

    @proc
    def each(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if title.startswith(title_prefix) or title.startswith(title_prefix.split(" ", 1)[-1] + " · "):
                found.append(hwnd)
        return True

    user32.EnumWindows(each, 0)
    insert = wintypes.HWND(-1 if on else -2)  # HWND_TOPMOST / HWND_NOTOPMOST
    done = 0
    for hwnd in found:  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        if user32.SetWindowPos(hwnd, insert, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010):
            done += 1
    return done


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
        if any(x in text for x in ("/api/ping", "/api/stream", "/api/console/ontop", "/sound/", "/img/", "/anim/", '"GET /overlay', "/api/state")):
            return
        log("HTTP " + text)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        path = urlsplit(self.path).path
        # Los videos de animación se pueden guardar en caché: así arrancan al instante y no se traban.
        self.send_header("Cache-Control", "max-age=86400" if path.startswith("/anim/") and path.lower().endswith(".webm") else "no-store")
        super().end_headers()

    def _local_request(self, overlay_ok: bool = False) -> bool:
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
        except ValueError:
            return False
        host = (urlsplit("//" + (self.headers.get("Host") or "")).hostname or "").lower()
        return host in LOCAL_HOSTS or (overlay_ok and host in OVERLAY_HOSTS)

    def _overlay_path(self) -> bool:
        path = urlsplit(self.path).path
        return path in OVERLAY_PATHS or path.startswith(OVERLAY_PREFIXES)

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
        if not self._local_request(overlay_ok=self._overlay_path()):
            self.send_error(403)
            return
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path in ("/", "/index.html"):
            html = (WEB_ROOT / "index.html").read_text(encoding="utf-8").replace('<html lang="es">', f'<html lang="{CONFIG["language"]}">', 1)
            self.send_file(WEB_ROOT / "index.html", html.encode("utf-8"))
        elif path in ("/overlay", "/overlay.html"):
            self.send_file(WEB_ROOT / "overlay.html")
        elif path in ("/consola", "/consola.html"):
            html = (WEB_ROOT / "consola.html").read_text(encoding="utf-8").replace('<html lang="es">', f'<html lang="{CONFIG["language"]}">', 1)
            self.send_file(WEB_ROOT / "consola.html", html.encode("utf-8"))
        elif path.startswith("/img/") and re.fullmatch(r"/img/[\w.-]+", path):
            target = WEB_ROOT / "img" / path.rsplit("/", 1)[-1]
            if target.is_file():
                self.send_file(target)
            else:
                self.send_error(404)
        elif path.startswith(("/metas/", "/mis-metas/")):
            target = action_image_path(("b/" if path.startswith("/metas/") else "u/") + unquote(path.rsplit("/", 1)[-1]))
            if target:
                self._send_bytes(target, mimetypes.guess_type(target.name)[0] or "image/png")
            else:
                self.send_error(404)
        elif path == "/api/actions/images":
            self.send_json({"ok": True, **action_images()})
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
        elif path == "/api/console":  # la consola flotante (no cuenta como «ventana abierta» para el actualizador)
            self.send_json({"console": CONFIG["console"], "lang": CONFIG["language"], "version": APP_VERSION})
        elif path == "/api/info":
            LAST_PING = time.time()
            self.send_json({"version": APP_VERSION, "build_date": BUILD_DATE, "config": CONFIG, "brb": BRB, "aliases": aliases_payload(),
                            "animations": list_animations(), "sound_bank": sound_bank(), "my_sounds": my_sounds(),
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
            UPDATER.check()  # si ya pasó una hora desde la última vez, vuelve a buscar (la ventana pregunta cada 10 min)
            self.send_json(UPDATER.public())
        else:
            self.send_json({"ok": False, "error": "No encontrado."}, 404)

    def _stream(self, who: str) -> None:
        """Eventos en tiempo real (la conexión se queda abierta)."""
        global LAST_PING
        sid, q = BUS.subscribe(who)
        if who == "overlay-brb":
            BUS.emit(new_event("brb", brb=brb_payload()))
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(b"retry: 2000\n\n")
            # La versión que está corriendo: si la ventana o un overlay traen otra (se actualizó EC-Tok), se recargan solos.
            self.wfile.write(f"data: {json.dumps(new_event('hello', version=APP_VERSION))}\n\n".encode("utf-8"))
            self.wfile.flush()
            # La fuente de «Ya regresamos» se revisa seguido: si la quitan de LIVE Studio, que vuelva a salir en la
            # de animaciones en segundos (no hasta que falle un envío).
            watch = who == "overlay-brb"
            last_write = time.time()
            while True:
                try:
                    event = q.get(timeout=3 if watch else 15)
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    if watch and _peer_closed(self.connection):
                        break
                    if watch and time.time() - last_write < 15:
                        continue
                    self.wfile.write(b": sigo aqui\n\n")
                self.wfile.flush()
                last_write = time.time()
                if who == "panel":  # solo la ventana de EC-Tok cuenta como «ventana abierta» (no los overlays de LIVE Studio)
                    LAST_PING = last_write
        except (ConnectionError, OSError):
            pass
        finally:
            BUS.unsubscribe(sid)
            if who == "overlay-brb":
                BUS.emit(new_event("brb", brb=brb_payload()))

    def _send_bytes(self, target: Path, ctype: str) -> None:
        size = target.stat().st_size
        start, end = 0, size - 1
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if rng and size and (rng.group(1) or rng.group(2)):  # los videos piden por pedazos
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with contextlib.suppress(ConnectionError, OSError), target.open("rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(256 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _send_sound(self, name: str) -> None:
        target = SOUNDS_DIR / Path(name).name
        if not target.is_file():
            target = SOUND_BANK / Path(name).name  # los de fábrica
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
            HOTKEYS.refresh()
            ectok_live.LANG["value"] = CONFIG["language"]
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
        elif path == "/api/sim/start":
            items = Simulator.clean(data.get("items"))
            if not items:
                self.send_json({"ok": False, "error": "Prende al menos una simulación."}, 400)
                return
            SIM.start(items, 5)  # se detiene sola a los 5 minutos, por si se te olvida
            self.send_json({"ok": True, "sim": SIM.public()})
        elif path == "/api/sim/stop":
            SIM.stop(bool(data.get("restore")), data.get("finish") is not False)
            self.send_json({"ok": True, "sim": SIM.public(), "live": LIVE.public(CONFIG["top"]["count"])})
        elif path == "/api/sim/status":
            self.send_json({"ok": True, "sim": SIM.public(), "live_state": LIVE.state})
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
            sample = {"name": _text(data.get("who"), "", 40), "avatar": ""} if data.get("who") else None
            trig = _text(data.get("trigger"), "", 20)
            fake = {"type": {"any_gift": "gift", "min_diamonds": "gift", "likes": "like"}.get(trig, trig),
                    "milestone": int(_num(data.get("every"), 0, 0, 10_000_000)) if trig == "user_likes" else 0,
                    "user": sample or {}, "gift": {"name": _text(data.get("caption"), "", 40) or "Heart Me", "count": 1, "total": 1}}
            label = _text(data.get("label"), "", 30)
            sign = sign_text(_text(data.get("text"), "", 120) or (label if data.get("quick") else ""), fake, bool(sample))
            BUS.emit(anim_event(file, float(_num(data.get("seconds"), a["quick_seconds"], 1, 30)),
                                int(_num(data.get("size"), a["quick_size"], 10, 100)), label, manual=True,
                                who=sample, caption=_text(data.get("caption"), "", 40), sign=sign) | {"preview": bool(data.get("preview"))})
            self.send_json({"ok": True})
        elif path == "/api/quick/fire":
            err = fire_button(_text(data.get("kind"), "", 10), _text(data.get("id"), "", 20), bool(data.get("preview")))
            self.send_json({"ok": not err, "error": err}, 404 if err else 200)
        elif path == "/api/hotkeys":
            self.send_json({"ok": True, **HOTKEYS.status()})
        elif path == "/api/brb":
            set_brb(bool(data.get("on")))
            self.send_json({"ok": True, "brb": BRB})
        elif path == "/api/anims/open":
            open_in_explorer(ANIM_USER)
            self.send_json({"ok": True})
        elif path == "/api/sound/delete":
            # Solo los tuyos (tu carpeta de sonidos); los del banco de EC-Tok no se borran.
            name = Path(str(data.get("file") or "")).name
            target = SOUNDS_DIR / name
            if not name or not target.is_file() or target.suffix.lower() not in SOUND_EXTS:
                self.send_json({"ok": False, "error": "No encontré ese sonido."}, 404)
                return
            target.unlink()
            with CONFIG_LOCK:
                CONFIG["console"]["sounds"] = [x for x in CONFIG["console"]["sounds"] if x.get("file") != name]
            save_config(CONFIG)
            self.send_json({"ok": True, "my_sounds": my_sounds(), "config": CONFIG})
        elif path == "/api/console/bank":
            # Volver a poner los 36 recomendados (6×6) que falten (no duplica ni quita los tuyos).
            with CONFIG_LOCK:
                c = CONFIG["console"]["sounds"]
                c += bank_console_items(CONFIG.get("language", "es"), {x.get("file") for x in c})
                del c[CONSOLE_MAX:]
            save_config(CONFIG)
            self.send_json({"ok": True, "config": CONFIG})
        elif path == "/api/sound/pick":
            if data.get("multi"):  # consola: varios a la vez
                chosen = _pick_file({"en": "Choose the sounds", "pt": "Escolha os sons"}.get(CONFIG["language"], "Elige los sonidos"),
                                    {"en": "Sounds", "pt": "Sons"}.get(CONFIG["language"], "Sonidos"), SOUND_EXTS,
                                    Path.home() / "Music", multi=True)[:CONSOLE_MAX]
                done, errors = [], []
                for item in chosen:
                    try:
                        done.append(import_sound(Path(item)))
                    except (ValueError, OSError) as exc:
                        errors.append(f"{Path(item).name}: {exc}")
                self.send_json({"ok": True, "sounds": done, "errors": errors})
                return
            chosen = pick_sound()
            if not chosen:
                self.send_json({"ok": True, "sound": None})
                return
            try:
                self.send_json({"ok": True, "sound": import_sound(Path(chosen))})
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/actions/add-images":
            chosen = _pick_file({"en": "Choose your images", "pt": "Escolha suas imagens"}.get(CONFIG["language"], "Elige tus imágenes"),
                                {"en": "Images", "pt": "Imagens"}.get(CONFIG["language"], "Imágenes"), ACTION_EXTS, Path.home() / "Pictures", multi=True)
            added, errors = [], []
            for item in chosen:
                try:
                    added.append(import_action_image(Path(item)))
                except (ValueError, OSError) as exc:
                    errors.append(f"{Path(item).name}: {exc}")
            self.send_json({"ok": True, "added": added, "errors": errors, **action_images()})
        elif path == "/api/actions/remove-image":
            image = str(data.get("id") or "")
            target = action_image_path(image)
            if not target or target.parent != ACTION_USER:
                self.send_json({"ok": False, "error": "Esa imagen no es tuya (las de fábrica no se borran)."}, 400)
                return
            with contextlib.suppress(OSError):
                target.unlink()
            for item in CONFIG["actions"]["items"]:
                if item["image"] == image:
                    item["image"] = ""
            save_config(CONFIG)
            BUS.emit(new_event("config", overlay=overlay_payload()))
            self.send_json({"ok": True, "config": CONFIG, **action_images()})
        elif path == "/api/bank/status":
            busy = BANK["state"] in ("downloading", "installing")
            if not busy and (data.get("check") or not BANK["checked"] or time.time() - BANK["checked_at"] > 3600):
                bank_check()  # al abrir la ventana, con el botón, y cada hora mientras está abierta
            self.send_json({"ok": True, "bank": bank_status()})
        elif path == "/api/bank/dismiss":  # «Ahora no»: no volver a invitar hasta que salga un banco más nuevo
            CONFIG["bank_dismissed"] = int(BANK["latest"] or 0)
            save_config(CONFIG)
            self.send_json({"ok": True, "bank": bank_status()})
        elif path == "/api/bank/download":
            if BANK["state"] not in ("downloading", "installing"):
                threading.Thread(target=_bank_download, daemon=True).start()
                BANK.update(state="downloading", percent=0.0, error="")
            self.send_json({"ok": True, "bank": bank_status()})
        elif path == "/api/bank/remove":
            bank_remove()
            self.send_json({"ok": True, "bank": bank_status(), "animations": list_animations()})
        elif path == "/api/console/open":
            open_app_window(f"http://127.0.0.1:{self.port}/consola", "760,600")
            self.send_json({"ok": True})
        elif path == "/api/console/ontop":
            on = bool(data.get("on"))
            if not data.get("refresh"):  # refresh: solo volver a subirla (la consola lo pide al perder el foco)
                with CONFIG_LOCK:
                    CONFIG["console"]["ontop"] = on
                save_config(CONFIG)
            n = set_topmost(CONSOLE_TITLE, on)
            if not data.get("refresh"):
                log(f"Consola: «siempre encima» {'sí' if on else 'no'} ({n} ventana(s))")
            self.send_json({"ok": True, "windows": n})
        elif path == "/api/anim/pick":
            # Paso 1: solo elegir (la ventana dice «elige el archivo»); paso 2: /api/anim/import convierte.
            chosen = pick_anim(multi=bool(data.get("multi")))[:20]
            ticket = uuid.uuid4().hex
            if chosen:
                PICKED[ticket] = chosen
            self.send_json({"ok": True, "ticket": ticket if chosen else None, "names": [Path(c).name for c in chosen]})
        elif path == "/api/anim/import":
            chosen = PICKED.pop(_text(data.get("ticket"), "", 40), [])  # solo lo que se eligió en el explorador
            files, errors = [], []
            for item in chosen:
                try:
                    files.append(import_anim(Path(item)))
                    with contextlib.suppress(OSError):
                        _set_anim_map(ANIM_ORIGIN_FILE, files[-1], str(item))
                    if data.get("name") and len(chosen) == 1:
                        set_anim_name(files[-1], _text(data.get("name"), "", 40))
                except (ValueError, OSError) as exc:
                    errors.append(f"{Path(item).name}: {exc}")
            if chosen and not files:
                self.send_json({"ok": False, "error": errors[0] if errors else "No se pudo."}, 400)
                return
            self.send_json({"ok": True, "file": files[0] if files else None, "files": files, "errors": errors,
                            "animations": list_animations()})
        elif path == "/api/anim/name":
            name = Path(str(data.get("file") or "")).name
            if not name or not (ANIM_USER / name).is_file():
                self.send_json({"ok": False, "error": "Solo puedes ponerle nombre a tus animaciones."}, 400)
                return
            set_anim_name(name, _text(data.get("name"), "", 40))
            label = anim_names().get(name) or anim_label(Path(name).stem)
            for sp in CONFIG["anims"]["special"]:  # los botones especiales con esa animación toman su nombre
                if sp.get("file") == name:
                    sp["label"] = label
            save_config(CONFIG)
            self.send_json({"ok": True, "animations": list_animations(), "config": CONFIG})
        elif path == "/api/anim/delete":
            # Solo las del streamer (su carpeta); las de EC-Tok no se borran.
            name = Path(str(data.get("file") or "")).name
            target = ANIM_USER / name
            if not name or not target.is_file() or target.suffix.lower() not in ANIM_EXTS:
                self.send_json({"ok": False, "error": "No encontré esa animación."}, 404)
                return
            target.unlink()
            with contextlib.suppress(OSError):
                _set_anim_map(ANIM_NAMES_FILE, name, "")
                _set_anim_map(ANIM_ORIGIN_FILE, name, "")
            self.send_json({"ok": True, "animations": list_animations()})
        elif path == "/api/special/play":
            specials = CONFIG["anims"]["special"]
            i = int(_num(data.get("i"), -1, -1, SPECIAL_MAX))
            sp = specials[i] if 0 <= i < len(specials) else None
            if not sp or not anim_path(sp["file"]):
                self.send_json({"ok": False, "error": "No encontré esa animación."}, 404)
                return
            BUS.emit(special_event(sp, bool(data.get("preview"))))
            self.send_json({"ok": True})
        elif path == "/api/special/stop":
            BUS.emit(new_event("special_stop"))
            self.send_json({"ok": True})
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
                  busy=lambda: "Estás conectado a un live: desconéctate primero." if LIVE.state == "live" else "",
                  extra_args=lambda: [f"/LANG={CONFIG['language']}"])


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
    parser.add_argument("--after-update", action="store_true", help=argparse.SUPPRESS)
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
    with contextlib.suppress(Exception):
        bank_defaults()  # quien ya tenía el banco instalado también recibe la regla y el botón de batalla
        bank_custom_defaults()
    HOTKEYS.start()
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
    if not args.no_browser and args.after_update:
        # Tras actualizar: si la ventana vieja no se pudo cerrar, se recarga sola con esta versión;
        # solo abrir una nueva si en unos segundos ninguna se reporta.
        started = time.time()
        threading.Timer(6, lambda: None if LAST_PING > started else open_app_window(url)).start()
    elif not args.no_browser:
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
