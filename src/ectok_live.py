"""Conexión con el LIVE de TikTok y todo lo que pasa en él.

- La conexión la hace la librería TikTokLive (no oficial): solo necesita el @usuario que está
  en vivo, sin contraseña. TikTok exige una «firma» que da el servicio Euler Stream (gratis,
  con límite de conexiones por hora; con una clave propia el límite es más alto).
- Cada cosa que pasa (regalo, follow, compartir, likes, comentario) se convierte en un evento
  sencillo (dict) que se manda a la ventana y a los overlays.
- También lleva la cuenta del live: likes, diamantes, follows, top de donadores.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import random
import threading
import time
from collections import deque
from typing import Callable

_ids = itertools.count(1)


def _get(obj, *paths, default=None):
    """Leer un dato que puede venir en distintos lugares según la versión de TikTokLive."""
    for path in paths:
        value = obj
        try:
            for part in path.split("."):
                if part.isdigit():
                    value = value[int(part)]
                else:
                    value = getattr(value, part)
        except (AttributeError, IndexError, KeyError, TypeError):
            continue
        if value not in (None, "", []):
            return value
    return default


def _user(u) -> dict:
    if u is None:
        return {"id": "", "name": "Alguien", "avatar": ""}
    uid = str(_get(u, "unique_id", "uniqueId", "display_id", default="") or "")
    name = str(_get(u, "nickname", "nick_name", default="") or uid or "Alguien")
    avatar = _get(u, "avatar_thumb.m_urls.0", "avatar_thumb.url_list.0", "avatar.m_urls.0", "profile_picture.m_urls.0",
                  "avatar_thumb.urls.0", default="")
    return {"id": uid, "name": name, "avatar": str(avatar or "")}


def new_event(kind: str, **data) -> dict:
    return {"id": next(_ids), "type": kind, "ts": time.time(), **data}


class Stats:
    """Lo que va pasando en el live (se reinicia al conectar)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.started = time.time()
        self.likes = self.diamonds = self.follows = self.shares = self.gifts = self.comments = 0
        self.donors: dict[str, dict] = {}
        self.gift_names: set[str] = set()

    def add(self, event: dict) -> None:
        with self.lock:
            kind = event["type"]
            if kind == "gift":
                gift = event["gift"]
                self.gifts += gift["count"]
                self.diamonds += gift["total"]
                self.gift_names.add(gift["name"])
                user = event["user"]
                key = user["id"] or user["name"]
                donor = self.donors.setdefault(key, {"name": user["name"], "avatar": user["avatar"], "diamonds": 0})
                donor["diamonds"] += gift["total"]
                donor["name"], donor["avatar"] = user["name"], user["avatar"] or donor["avatar"]
            elif kind == "like":
                total = event.get("total_likes") or 0
                self.likes = max(self.likes + event.get("count", 0), total)
            elif kind == "follow":
                self.follows += 1
            elif kind == "share":
                self.shares += 1
            elif kind == "comment":
                self.comments += 1

    def public(self, top: int = 10) -> dict:
        with self.lock:
            donors = sorted(self.donors.values(), key=lambda d: d["diamonds"], reverse=True)[:top]
            return {"likes": self.likes, "diamonds": self.diamonds, "follows": self.follows, "shares": self.shares,
                    "gifts": self.gifts, "comments": self.comments, "top": donors, "started": self.started,
                    "gift_names": sorted(self.gift_names)}


class Live:
    """Conexión al live de un @usuario, en su propio hilo (asyncio)."""

    RETRY_SECONDS = 30  # si todavía no está en vivo o se cae: volver a intentar (sin gastar la cuota de Euler)

    def __init__(self, emit: Callable[[dict], None], log: Callable[[str], None]) -> None:
        self.emit, self.log = emit, log
        self.stats = Stats()
        self.state = "idle"      # idle, connecting, waiting (no está en vivo), live, error
        self.message = ""
        self.username = ""
        self.want = False        # el usuario pidió estar conectado
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client = None
        self.recent: deque[dict] = deque(maxlen=200)
        self.lock = threading.Lock()

    # ---------- estado ----------
    def public(self, top: int = 10) -> dict:
        return {"state": self.state, "message": self.message, "username": self.username,
                "stats": self.stats.public(top)}

    def _set(self, state: str, message: str = "") -> None:
        self.state, self.message = state, message
        self.emit(new_event("status", state=state, message=message, username=self.username))

    def push(self, event: dict) -> None:
        """Un evento del live (o de prueba): contarlo y mandarlo."""
        self.stats.add(event)
        self.recent.append(event)
        self.emit({**event, "stats": self.stats.public(10)})  # los overlays de metas y top se actualizan con esto

    # ---------- conectar / desconectar ----------
    def connect(self, username: str, api_key: str = "") -> None:
        username = username.strip().lstrip("@").strip()
        if not username:
            raise ValueError("Escribe tu @usuario de TikTok.")
        self.disconnect()
        with self.lock:
            self.username, self.want = username, True
            self.stats.reset()
            self.thread = threading.Thread(target=self._thread, args=(username, api_key), daemon=True)
            self.thread.start()

    def disconnect(self) -> None:
        self.want = False
        loop, client = self.loop, self.client
        if loop and client:
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(client.disconnect(), loop).result(timeout=5)
        thread = self.thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=6)
        self.thread = None
        if self.state != "idle":
            self._set("idle", "Desconectado.")

    def _thread(self, username: str, api_key: str) -> None:
        loop = asyncio.new_event_loop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        try:
            while self.want:
                try:
                    loop.run_until_complete(self._session(username, api_key))
                except Exception as exc:  # noqa: BLE001
                    text = str(exc) or exc.__class__.__name__
                    self.log(f"[live] {exc.__class__.__name__}: {text}")
                    if not self.want:
                        break
                    if "offline" in text.lower() or "not live" in text.lower() or exc.__class__.__name__ in ("UserOfflineError",):
                        self._set("waiting", f"@{username} no está en vivo. Vuelvo a intentar cada {self.RETRY_SECONDS} s…")
                    elif "UserNotFound" in exc.__class__.__name__:
                        self._set("error", f"No existe la cuenta @{username}. Revisa el usuario.")
                        self.want = False
                        break
                    elif "rate" in text.lower() or "limit" in text.lower() or "429" in text:
                        self._set("waiting", "Se alcanzó el límite gratis de conexiones de Euler Stream. Espera un rato "
                                             "o pon tu clave de Euler en Ajustes.")
                    else:
                        self._set("waiting", f"No se pudo conectar ({text[:120]}). Vuelvo a intentar en {self.RETRY_SECONDS} s…")
                else:
                    if self.want:
                        self._set("waiting", f"El live terminó o se cortó. Vuelvo a intentar en {self.RETRY_SECONDS} s…")
                for _ in range(self.RETRY_SECONDS * 2):
                    if not self.want:
                        break
                    time.sleep(0.5)
        finally:
            self.client = None
            with contextlib.suppress(Exception):
                loop.close()
            self.loop = None

    async def _session(self, username: str, api_key: str) -> None:
        from TikTokLive import TikTokLiveClient  # type: ignore[import-not-found]
        from TikTokLive.events import (  # type: ignore[import-not-found]
            CommentEvent, ConnectEvent, DisconnectEvent, FollowEvent, GiftEvent, LikeEvent, LiveEndEvent, ShareEvent,
        )

        if api_key:
            with contextlib.suppress(Exception):
                from TikTokLive.client.web.web_settings import WebDefaults  # type: ignore[import-not-found]

                WebDefaults.tiktok_sign_api_key = api_key
        self._set("connecting", f"Conectando con @{username}…")
        client = TikTokLiveClient(unique_id=username)
        self.client = client

        @client.on(ConnectEvent)
        async def _connected(_event) -> None:
            self._set("live", f"Conectado al live de @{username}.")
            self.log(f"[live] conectado a @{username}")

        @client.on(DisconnectEvent)
        async def _disconnected(_event) -> None:
            self.log("[live] desconectado")

        @client.on(LiveEndEvent)
        async def _ended(_event) -> None:
            self.emit(new_event("system", text="El live terminó."))

        @client.on(GiftEvent)
        async def _gift(event) -> None:
            gift = getattr(event, "gift", None)
            if gift is None:
                return
            streakable = _get(gift, "streakable", default=None)
            if streakable is None:
                streakable = _get(gift, "type", default=0) == 1
            if streakable and bool(_get(event, "streaking", default=False)):
                return  # todavía va la racha: avisar solo al terminar
            count = int(_get(event, "repeat_count", default=1) or 1)
            each = int(_get(gift, "diamond_count", "info.diamond_count", default=0) or 0)
            self.push(new_event("gift", user=_user(getattr(event, "user", None)), gift={
                "name": str(_get(gift, "name", "info.name", default="Regalo")), "count": count, "diamonds": each,
                "total": each * count,
                "image": str(_get(gift, "image.m_urls.0", "image.url_list.0", "info.image.m_urls.0", "icon.m_urls.0", default="") or ""),
            }))

        @client.on(FollowEvent)
        async def _follow(event) -> None:
            self.push(new_event("follow", user=_user(getattr(event, "user", None))))

        @client.on(ShareEvent)
        async def _share(event) -> None:
            self.push(new_event("share", user=_user(getattr(event, "user", None))))

        @client.on(LikeEvent)
        async def _like(event) -> None:
            self.push(new_event("like", user=_user(getattr(event, "user", None)),
                                count=int(_get(event, "count", "like_count", default=1) or 1),
                                total_likes=int(_get(event, "total", "total_likes", "total_like_count", default=0) or 0)))

        @client.on(CommentEvent)
        async def _comment(event) -> None:
            self.push(new_event("comment", user=_user(getattr(event, "user", None)),
                                text=str(_get(event, "comment", "content", default="") or "")))

        await client.connect()


# ---------------------------------------------------------------------------
# Modo prueba: eventos falsos para ver alertas, sonidos y voz sin estar en vivo
# ---------------------------------------------------------------------------
TEST_USERS = ["Ana López", "carlitos_mx", "La Chula", "DJ Pepe", "maria.fer", "El Compa"]
TEST_GIFTS = [("Rose", 1), ("TikTok", 1), ("GG", 1), ("Heart Me", 1), ("Finger Heart", 5), ("Doughnut", 30),
              ("Hand Hearts", 100), ("Corgi", 299), ("Money Gun", 500), ("Lion", 29999), ("Universe", 34999)]


def test_event(kind: str, gift: str = "") -> dict:
    name = random.choice(TEST_USERS)
    user = {"id": name.replace(" ", "_").lower(), "name": name, "avatar": ""}
    if kind == "gift":
        options = [g for g in TEST_GIFTS if g[0].lower() == gift.lower()] or [random.choice(TEST_GIFTS[:8])]
        gname, each = options[0]
        count = random.choice([1, 1, 3, 5, 10]) if each < 100 else 1
        return new_event("gift", user=user, test=True,
                         gift={"name": gname, "count": count, "diamonds": each, "total": each * count, "image": ""})
    if kind == "like":
        return new_event("like", user=user, count=random.choice([15, 30, 50]), total_likes=0, test=True)
    if kind == "comment":
        text = random.choice(["¡Hola a todos!", "Saludos desde Monterrey 🔥", "Esa canción está buenísima",
                              "¿Cantas la de Marlboro Rojo?", "Qué bonito live"])
        return new_event("comment", user=user, text=text, test=True)
    return new_event(kind if kind in ("follow", "share") else "follow", user=user, test=True)
