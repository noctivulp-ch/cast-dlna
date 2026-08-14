"""GENA: suscripciones de eventos y NOTIFY con LastChange.

Sin eventing el controlador solo ve el estado si hace polling, y varios
(incluido Web Video Caster) dependen de las notificaciones para refrescar
la barra de progreso y los botones play/pausa.
"""

import http.client
import re
import threading
import time
import urllib.parse
import uuid
from xml.sax.saxutils import escape

DEFAULT_TIMEOUT = 1800

LASTCHANGE_NS = {
    "AVTransport": "urn:schemas-upnp-org:metadata-1-0/AVT/",
    "RenderingControl": "urn:schemas-upnp-org:metadata-1-0/RCS/",
}

# Variables cuyo valor lleva el atributo `channel` en RenderingControl.
CHANNEL_VARS = ("Volume", "Mute", "VolumeDB", "Loudness")


class Subscription:
    def __init__(self, sid, callbacks, timeout):
        self.sid = sid
        self.callbacks = callbacks
        self.expires = time.time() + timeout
        self.seq = 0


class EventManager:
    """Maneja las suscripciones de un servicio concreto."""

    def __init__(self, cfg, service_name):
        self.cfg = cfg
        self.service = service_name
        self.subs = {}
        self.lock = threading.Lock()
        threading.Thread(target=self._reaper, daemon=True).start()

    # ── Suscripciones ──────────────────────────────────────────────────────
    def subscribe(self, callback_header, timeout_header, initial_state):
        callbacks = re.findall(r"<([^>]+)>", callback_header or "")
        if not callbacks:
            return None, 0
        timeout = _parse_timeout(timeout_header)
        sid = "uuid:" + str(uuid.uuid4())
        sub = Subscription(sid, callbacks, timeout)
        with self.lock:
            self.subs[sid] = sub
        self.cfg.debug(f"[gena:{self.service}] SUBSCRIBE {sid} → {callbacks[0]}")
        threading.Thread(target=self._send, args=(sub, initial_state),
                         daemon=True).start()
        return sid, timeout

    def renew(self, sid, timeout_header):
        with self.lock:
            sub = self.subs.get(sid)
            if not sub:
                return None, 0
            timeout = _parse_timeout(timeout_header)
            sub.expires = time.time() + timeout
        return sid, timeout

    def unsubscribe(self, sid):
        with self.lock:
            return self.subs.pop(sid, None) is not None

    def _reaper(self):
        while True:
            time.sleep(30)
            now = time.time()
            with self.lock:
                dead = [sid for sid, sub in self.subs.items() if sub.expires < now]
                for sid in dead:
                    del self.subs[sid]

    # ── Envío ──────────────────────────────────────────────────────────────
    def publish(self, state):
        """Notifica un cambio a todos los suscriptores del servicio."""
        with self.lock:
            targets = list(self.subs.values())
        for sub in targets:
            threading.Thread(target=self._send, args=(sub, state),
                             daemon=True).start()

    def _send(self, sub, state):
        if not state:
            return
        body = self._body(state)
        with self.lock:
            seq = sub.seq
            sub.seq = (sub.seq + 1) % 0x100000000
        for url in sub.callbacks:
            if self._post(url, sub.sid, seq, body):
                return
        self.cfg.debug(f"[gena:{self.service}] NOTIFY falló para {sub.sid}")

    def _body(self, state):
        ns = LASTCHANGE_NS.get(self.service)
        if ns is None:
            props = "".join(
                f"<e:property><{name}>{escape(str(value))}</{name}></e:property>"
                for name, value in state.items())
            return _propertyset(props)
        inner = []
        for name, value in state.items():
            channel = ' channel="Master"' if name in CHANNEL_VARS else ""
            val = escape(str(value), {'"': "&quot;"})
            inner.append(f'<{name}{channel} val="{val}"/>')
        last_change = (f'<Event xmlns="{ns}"><InstanceID val="0">'
                       f'{"".join(inner)}</InstanceID></Event>')
        return _propertyset(
            f"<e:property><LastChange>{escape(last_change)}</LastChange></e:property>")

    def _post(self, url, sid, seq, body):
        parsed = urllib.parse.urlparse(url)
        if not parsed.hostname:
            return False
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        try:
            conn = http.client.HTTPConnection(
                parsed.hostname, parsed.port or 80, timeout=5)
            conn.request("NOTIFY", path, body.encode("utf-8"), {
                "Content-Type": 'text/xml; charset="utf-8"',
                "NT": "upnp:event",
                "NTS": "upnp:propchange",
                "SID": sid,
                "SEQ": str(seq),
                "Connection": "close",
            })
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return 200 <= resp.status < 300
        except Exception:
            return False


def _propertyset(props):
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
            f'{props}</e:propertyset>')


def _parse_timeout(header):
    m = re.search(r"Second-(\d+)", header or "", re.I)
    if m:
        return max(60, min(int(m.group(1)), 7200))
    return DEFAULT_TIMEOUT
