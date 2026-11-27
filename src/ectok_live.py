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
import re
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


def _dget(obj, *paths, default=None):
    """Como _get, pero también entra a diccionarios (las respuestas web de TikTok vienen como JSON)."""
    for path in paths:
        value = obj
        try:
            for part in path.split("."):
                if part.isdigit():
                    value = value[int(part)]
                elif isinstance(value, dict):
                    value = value[part]
                else:
                    value = getattr(value, part)
        except (AttributeError, IndexError, KeyError, TypeError):
            continue
        if value not in (None, "", []):
            return value
    return default


IMAGE_PATHS = ("image.url_list.0", "image.m_urls.0", "image.urlList.0", "info.image.url_list.0", "info.image.m_urls.0",
               "icon.url_list.0", "icon.m_urls.0")


def gift_info(g) -> dict | None:
    """Nombre, monedas e imagen oficial de un regalo (de un evento o del catálogo). None si no se puede leer."""
    name = _dget(g, "name", "info.name")
    if not name:
        return None
    return {"name": str(name)[:60], "diamonds": int(_dget(g, "diamond_count", "diamondCount", "info.diamond_count", default=0) or 0),
            "image": str(_dget(g, *IMAGE_PATHS, default="") or "")}


def find_gifts(data, depth: int = 0) -> list[dict]:
    """Buscar la lista de regalos dentro de lo que regrese TikTok, venga como venga (JSON u objetos)."""
    if depth > 5 or data is None:
        return []
    if isinstance(data, (list, tuple)):
        found = [g for g in (gift_info(x) for x in data) if g and g["image"]]
        if found:
            return found
        out: list[dict] = []
        for x in data[:50]:
            out += find_gifts(x, depth + 1)
        return out
    if isinstance(data, dict):
        for key in ("gifts", "data", "gift_list", "giftList"):
            if key in data:
                got = find_gifts(data[key], depth + 1)
                if got:
                    return got
        return []
    for key in ("gifts", "data", "gift_list"):
        sub = getattr(data, key, None)
        if sub is not None:
            got = find_gifts(sub, depth + 1)
            if got:
                return got
    return []


def _user(u) -> dict:
    if u is None:
        return {"id": "", "name": "Alguien", "avatar": ""}
    uid = str(_get(u, "unique_id", "uniqueId", "display_id", default="") or "")
    name = str(_get(u, "nickname", "nick_name", default="") or uid or "Alguien")
    avatar = _get(u, "avatar_thumb.m_urls.0", "avatar_thumb.url_list.0", "avatar.m_urls.0", "profile_picture.m_urls.0",
                  "avatar_thumb.urls.0", default="")
    return {"id": uid, "name": name, "avatar": str(avatar or "")}


# Mensajes del estado de la conexión, en el idioma de la app.
MESSAGES = {
    "connecting": {"es": "Conectando con @{u}…", "en": "Connecting to @{u}…", "pt": "Conectando com @{u}…", "zh": "正在连接 @{u}…"},
    "live": {"es": "Conectado al live de @{u}.", "en": "Connected to @{u}'s LIVE.", "pt": "Conectado à live de @{u}.", "zh": "已连接到 @{u} 的直播。"},
    "offline": {"es": "@{u} no está en vivo. Vuelvo a intentar cada {s} s…", "en": "@{u} is not live. Trying again every {s} s…",
                "pt": "@{u} não está ao vivo. Tento de novo a cada {s} s…", "zh": "@{u} 没有在直播。每 {s} 秒重试一次…"},
    "notfound": {"es": "No existe la cuenta @{u}. Revisa el usuario.", "en": "The account @{u} does not exist. Check the username.",
                 "pt": "A conta @{u} não existe. Confira o usuário.", "zh": "账号 @{u} 不存在。请检查用户名。"},
    "ratelimit": {"es": "Se alcanzó el límite gratis de conexiones de Euler Stream. Espera un rato o pon tu clave de Euler en Ajustes.",
                  "en": "The free Euler Stream connection limit was reached. Wait a while or add your Euler key in Settings.",
                  "pt": "O limite grátis de conexões do Euler Stream foi atingido. Espere um pouco ou coloque sua chave do Euler em Ajustes.", "zh": "已达到 Euler Stream 的免费连接上限。请稍等一会儿，或在设置中填入你的 Euler 密钥。"},
    "failed": {"es": "No se pudo conectar ({e}). Vuelvo a intentar en {s} s…", "en": "Could not connect ({e}). Trying again in {s} s…",
               "pt": "Não foi possível conectar ({e}). Tento de novo em {s} s…", "zh": "无法连接（{e}）。{s} 秒后重试…"},
    "ended": {"es": "El live terminó o se cortó. Vuelvo a intentar en {s} s…", "en": "The LIVE ended or dropped. Trying again in {s} s…",
              "pt": "A live terminou ou caiu. Tento de novo em {s} s…", "zh": "直播结束或中断了。{s} 秒后重试…"},
    "disconnected": {"es": "Desconectado.", "en": "Disconnected.", "pt": "Desconectado.", "zh": "已断开连接。"},
    "live_end": {"es": "El live terminó.", "en": "The LIVE ended.", "pt": "A live terminou.", "zh": "直播结束了。"},
    "need_user": {"es": "Escribe tu @usuario de TikTok.", "en": "Type your TikTok @username.", "pt": "Escreva seu @usuário do TikTok.", "zh": "请输入你的 TikTok @用户名。"},
}
LANG = {"value": "es"}  # idioma de la ventana de EC-Tok (avisos de conexión)
LIVE_LANG = {"value": "es"}  # idioma del live (comentarios de prueba)


def msg(key: str, **kw) -> str:
    table = MESSAGES[key]
    return table.get(LANG["value"], table["es"]).format(**kw)


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
        self.viewers = 0  # 5.3.0: espectadores en este momento (para «Ya casi iniciamos»)
        self.donors: dict[str, dict] = {}
        self.likers: dict[str, dict] = {}
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
                user = event.get("user") or {}
                key = user.get("id") or user.get("name")
                if key and user.get("name") != "Alguien":
                    liker = self.likers.setdefault(key, {"name": user["name"], "avatar": user.get("avatar", ""), "likes": 0})
                    liker["likes"] += int(event.get("count") or 0)
                    liker["name"], liker["avatar"] = user["name"], user.get("avatar") or liker["avatar"]
            elif kind == "follow":
                self.follows += 1
            elif kind == "share":
                self.shares += 1
            elif kind == "comment":
                self.comments += 1

    def public(self, top: int = 10) -> dict:
        with self.lock:
            donors = sorted(self.donors.values(), key=lambda d: d["diamonds"], reverse=True)[:top]
            likers = sorted(self.likers.values(), key=lambda d: d["likes"], reverse=True)[:10]
            return {"likes": self.likes, "diamonds": self.diamonds, "follows": self.follows, "shares": self.shares,
                    "gifts": self.gifts, "comments": self.comments, "viewers": self.viewers, "top": donors, "likers": likers, "started": self.started,
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
        self.on_gifts: Callable[..., None] | None = None  # recibe el catálogo de regalos (nombre, monedas, imagen); replace=True: es la lista nueva de este live

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
        if event.get("type") in ("join", "viewers"):  # 5.3.0: solo para «Ya casi iniciamos» (no van al feed ni al historial)
            self.emit(event)
            return
        self.stats.add(event)
        self.recent.append(event)
        self.emit({**event, "stats": self.stats.public(10)})  # los overlays de metas y top se actualizan con esto

    # ---------- conectar / desconectar ----------
    def connect(self, username: str, api_key: str = "") -> None:
        username = username.strip().lstrip("@").strip()
        if not username:
            raise ValueError(msg("need_user"))
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
            self._set("idle", msg("disconnected"))

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
                        self._set("waiting", msg("offline", u=username, s=self.RETRY_SECONDS))
                    elif "UserNotFound" in exc.__class__.__name__:
                        self._set("error", msg("notfound", u=username))
                        self.want = False
                        break
                    elif "rate" in text.lower() or "limit" in text.lower() or "429" in text:
                        self._set("waiting", msg("ratelimit"))
                    else:
                        self._set("waiting", msg("failed", e=text[:120], s=self.RETRY_SECONDS))
                else:
                    if self.want:
                        self._set("waiting", msg("ended", s=self.RETRY_SECONDS))
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
        self._set("connecting", msg("connecting", u=username))
        client = TikTokLiveClient(unique_id=username)
        self.client = client

        @client.on(ConnectEvent)
        async def _connected(_event) -> None:
            self._set("live", msg("live", u=username))
            self.log(f"[live] conectado a @{username}")
            asyncio.ensure_future(self._fetch_gifts(client, replace=True))  # la lista de ESTE live (cada streamer puede tener otros regalos)

        @client.on(DisconnectEvent)
        async def _disconnected(_event) -> None:
            self.log("[live] desconectado")

        @client.on(LiveEndEvent)
        async def _ended(_event) -> None:
            self.emit(new_event("system", text=msg("live_end")))

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
            info = gift_info(gift)
            if info and info["image"] and self.on_gifts:  # cada regalo que llega también enseña su imagen oficial
                with contextlib.suppress(Exception):
                    self.on_gifts([info])
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

        self._extra_events(client)
        await client.connect()

    def refresh_gifts(self, timeout: float = 25) -> int:
        """🔄 Volver a pedirle a TikTok la lista de regalos del live al que estás conectado. Regresa cuántos llegaron."""
        loop, client = self.loop, self.client
        if self.state != "live" or not loop or not client:
            raise ValueError("Primero conéctate a tu live: la lista de regalos la manda TikTok para ese live.")
        got = asyncio.run_coroutine_threadsafe(self._fetch_gifts(client, replace=True), loop).result(timeout=timeout)
        if not got:
            raise ValueError("TikTok no mandó la lista de regalos. Intenta otra vez en un momento.")
        return got

    async def _fetch_gifts(self, client, replace: bool = False) -> int:
        """Pedir a TikTok el catálogo de regalos del live (nombre, monedas y dirección de su imagen oficial).
        Las imágenes no se guardan: se muestran desde TikTok. Si la librería no lo tiene o falla, no pasa nada:
        el catálogo se va llenando con los regalos que llegan."""
        if not self.on_gifts:
            return 0
        web = getattr(client, "web", None)
        room = getattr(client, "room_id", None)
        for name in ("fetch_gift_list", "fetch_gifts", "gift_list"):
            fn = getattr(web, name, None) if web is not None else None
            if not callable(fn):
                continue
            try:
                try:
                    result = fn(room_id=room) if room else fn()  # la del cuarto de este live, si la librería lo permite
                except TypeError:
                    result = fn()
                if asyncio.iscoroutine(result):
                    result = await result
                gifts = find_gifts(result)
                if gifts:
                    self.on_gifts(gifts, replace=replace)
                    self.log(f"[live] catálogo de regalos: {len(gifts)} con imagen oficial")
                    return len(gifts)
            except Exception as exc:  # noqa: BLE001
                self.log(f"[live] no se pudo leer el catálogo de regalos ({name}): {exc}")
        self.log("[live] la librería no dio el catálogo de regalos; se llenará con los regalos que lleguen")
        return 0

    # ---------- eventos «especiales» (suscripción, cofre, batallas…) ----------
    def _extra_events(self, client) -> None:
        """Estos eventos cambian seguido en TikTok y casi no están documentados: se toman con cuidado
        (si una versión de la librería no los trae, no pasa nada) y los primeros se guardan en el
        registro para poder afinarlos."""
        import TikTokLive.events as ev  # type: ignore[import-not-found]

        seen: dict[str, int] = {}
        last: dict[str, float] = {}

        def raw(name: str, event) -> str:
            text = ""
            with contextlib.suppress(Exception):
                text = repr(event)
            if seen.get(name, 0) < 8:  # guardar algunos en el registro (para afinar)
                seen[name] = seen.get(name, 0) + 1
                self.log(f"[evento {name}] {text[:1500]}")
            return text

        def once(key: str, seconds: float) -> bool:
            now = time.time()
            if now - last.get(key, 0) < seconds:
                return False
            last[key] = now
            return True

        def on(name: str, handler) -> None:
            cls = getattr(ev, name, None)
            if cls is None:
                return
            if hasattr(client, "add_listener"):
                client.add_listener(cls, handler)
            else:
                client.on(cls)(handler)

        async def subscribe(event) -> None:
            raw("SubNotifyEvent", event)
            self.push(new_event("subscribe", user=_user(getattr(event, "user", None))))

        async def superfan(event) -> None:
            raw("SuperFan", event)
            self.push(new_event("superfan", user=_user(getattr(event, "user", None))))

        async def envelope(event) -> None:
            raw("EnvelopeEvent", event)
            if once("envelope", 5):
                self.push(new_event("envelope", user=_user(_get(event, "user", "envelope_info.send_user", default=None))))

        async def battle(event) -> None:
            text = raw("LinkMicBattleEvent", event)
            ended = bool(re.search(r"(finish|end|result|winner)", text, re.I)) and not re.search(r"start", text, re.I)
            phase = "end" if ended else "start"
            if once("battle_" + phase, 45):
                self.push(new_event("battle", phase=phase))

        async def battle_end(event) -> None:
            raw("LinkMicBattlePunishFinishEvent", event)
            if once("battle_end", 45):
                self.push(new_event("battle", phase="end"))

        async def booster(event) -> None:
            text = raw(event.__class__.__name__, event)
            match = re.search(r"\b[xX]\s?([2-5])\b", text) or re.search(r"multipl\w*\D{0,25}([2-5])\b", text, re.I)
            mult = int(match.group(1)) if match else 0
            if once(f"booster_{mult}", 8):
                self.push(new_event("booster", multiplier=mult, user=_user(getattr(event, "user", None))))

        async def viewers(event) -> None:  # 5.3.0: cuántos están viendo (para «Ya casi iniciamos»)
            raw("RoomUserSeqEvent", event)
            n = _get(event, "m_total", "total_user", "total", "viewer_count", default=0)
            with contextlib.suppress(TypeError, ValueError):
                self.stats.viewers = int(n or 0)
                if once("viewers", 3):
                    self.push(new_event("viewers", count=self.stats.viewers))

        async def join(event) -> None:  # 5.3.0: alguien entró al live (sala de espera de «Ya casi iniciamos»)
            raw("JoinEvent", event)
            self.push(new_event("join", user=_user(getattr(event, "user", None))))

        on("RoomUserSeqEvent", viewers)
        on("JoinEvent", join)
        on("SubNotifyEvent", subscribe)
        for name in ("SuperFanEvent", "SuperFanJoinEvent"):
            on(name, superfan)
        for name in ("EnvelopeEvent", "SuperFanBoxEvent"):
            on(name, envelope)
        on("LinkMicBattleEvent", battle)
        on("LinkMicBattlePunishFinishEvent", battle_end)
        for name in ("LinkMicBattleItemCardEvent", "BoostCardEvent"):
            on(name, booster)


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
        options = ([g for g in TEST_GIFTS if g[0].lower() == gift.lower()] or ([(gift, 1)] if gift.strip() else [])
                   or [random.choice(TEST_GIFTS[:8])])
        gname, each = options[0]
        # Heart Me: TikTok solo deja mandar uno al día por persona.
        count = 1 if each >= 100 or gname.lower() == "heart me" else random.choice([1, 1, 3, 5, 10])
        return new_event("gift", user=user, test=True,
                         gift={"name": gname, "count": count, "diamonds": each, "total": each * count, "image": ""})
    if kind == "like":
        return new_event("like", user=user, count=random.choice([15, 30, 50]), total_likes=0, test=True)
    if kind in ("subscribe", "superfan", "envelope"):
        return new_event(kind, user=user, test=True)
    if kind == "battle":
        return new_event("battle", phase=gift or "start", test=True)
    if kind == "booster":
        return new_event("booster", multiplier=int(gift or 3), user=user, test=True)
    if kind == "comment":
        samples = {"es": ["¡Hola a todos!", "Saludos desde Monterrey 🔥", "Esa canción está buenísima", "¿Cantas otra?", "Qué bonito live"],
                   "en": ["Hi everyone!", "Greetings from Texas 🔥", "That song is great", "Can you sing another one?", "Lovely LIVE"],
                   "pt": ["Oi, gente!", "Saudações de São Paulo 🔥", "Essa música é demais", "Canta outra?", "Que live linda"], "zh": ["大家好！", "来自上海的问候 🔥", "这首歌太好听了", "再唱一首吧？", "好棒的直播"]}
        text = random.choice(samples.get(LIVE_LANG["value"], samples["es"]))
        return new_event("comment", user=user, text=text, test=True)
    return new_event(kind if kind in ("follow", "share") else "follow", user=user, test=True)
