"""Servidor HTTP UPnP: descriptores, control SOAP y suscripciones GENA."""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import device, soap
from .renderer import UPnPFault

# PNG 48x48 de un solo color — algunos controladores piden el icono declarado
# y registran un error si devuelve 404.
ICON_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAIAAABvSEP3AAAAPUlEQVR42u3OMQEAAAgDoC1"
    b"ZNRTwK4EGuHfaBAKBQCAQCAQCgUAgEAgEAoFAIBAIBAKBQCAQCAQCwYcFC7wAAdE9pRIAAAA"
    b"ASUVORK5CYII=")

SERVICES = {
    "avt": ("AVTransport", device.AVT),
    "rcs": ("RenderingControl", device.RCS),
    "cms": ("ConnectionManager", device.CMS),
}


class UPnPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Linux/1.0 UPnP/1.0 cast-dlna/1.0"

    # ── Infra ──────────────────────────────────────────────────────────────
    @property
    def cfg(self):
        return self.server.cfg

    def log_message(self, fmt, *args):
        self.cfg.debug("[http] " + fmt % args)

    def _send(self, code, ctype, body=b"", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        # Una respuesta a HEAD lleva Content-Length pero nunca cuerpo: con
        # keep-alive de HTTP/1.1 el cliente leería ese cuerpo como el inicio
        # de la respuesta siguiente y la conexión se descarrila. CastLab
        # comprueba la accesibilidad del dispositivo con HEAD /device.xml en
        # cada ciclo de polling, así que esto lo desconectaba al reproducir.
        if body and self.command != "HEAD":
            self.wfile.write(body)

    # ── GET / HEAD ─────────────────────────────────────────────────────────
    def do_GET(self):
        routes = {
            "/device.xml": ("text/xml; charset=\"utf-8\"", device.device_xml(self.cfg)),
            "/scpd/avt.xml": ("text/xml; charset=\"utf-8\"", device.AVT_SCPD),
            "/scpd/rcs.xml": ("text/xml; charset=\"utf-8\"", device.RCS_SCPD),
            "/scpd/cms.xml": ("text/xml; charset=\"utf-8\"", device.CMS_SCPD),
        }
        if self.path in routes:
            ctype, body = routes[self.path]
            self._send(200, ctype, body)
        elif self.path == "/icon.png":
            self._send(200, "image/png", ICON_PNG)
        elif self.path in ("/", "/status"):
            self._send(200, "text/plain; charset=utf-8", self._status_text())
        else:
            self._send(404, "text/plain", "Not Found")

    def do_HEAD(self):
        self.do_GET()

    def _status_text(self):
        r = self.server.renderer
        return (f"cast-dlna — {self.cfg.name}\n"
                f"estado : {r.player.transport_state}\n"
                f"uri    : {r.uri}\n"
                f"pos    : {r._position_str()} / {r._duration_str()}\n"
                f"volumen: {r.player.volume}{' (mute)' if r.player.muted else ''}\n")

    # ── POST (control SOAP) ────────────────────────────────────────────────
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        key = self.path.rsplit("/", 1)[-1]
        if not self.path.startswith("/ctrl/") or key not in SERVICES:
            self._send(404, "text/plain", "Not Found")
            return

        service_name, service_type = SERVICES[key]
        action, args = soap.parse_action(self.headers.get("SOAPAction", ""), body)
        self.cfg.debug(f"[soap] {service_name}.{action} {args}")

        renderer = self.server.renderer
        dispatch = {"AVTransport": renderer.avt,
                    "RenderingControl": renderer.rcs,
                    "ConnectionManager": renderer.cms}[service_name]
        try:
            values = dispatch(action, args)
        except UPnPFault as exc:
            self._send(500, "text/xml; charset=\"utf-8\"",
                       soap.fault(exc.code, exc.description))
            return
        except Exception as exc:
            self.cfg.log(f"[error] {service_name}.{action}: {exc}")
            self._send(500, "text/xml; charset=\"utf-8\"", soap.fault(501, str(exc)))
            return

        if values is None:
            self.cfg.debug(f"[soap] acción no soportada: {action}")
            self._send(500, "text/xml; charset=\"utf-8\"", soap.fault(401))
            return
        self._send(200, "text/xml; charset=\"utf-8\"",
                   soap.response(action, service_type, values))

    # ── GENA ───────────────────────────────────────────────────────────────
    def do_SUBSCRIBE(self):
        key = self.path.rsplit("/", 1)[-1]
        if not self.path.startswith("/evt/") or key not in SERVICES:
            self._send(404, "text/plain", "Not Found")
            return
        service_name, _ = SERVICES[key]
        manager = self.server.events[service_name]
        sid = self.headers.get("SID")

        if sid:
            sid, timeout = manager.renew(sid, self.headers.get("TIMEOUT"))
            if not sid:
                self._send(412, "text/plain", "Precondition Failed")
                return
        else:
            initial = self.server.initial_state(service_name)
            sid, timeout = manager.subscribe(
                self.headers.get("CALLBACK"), self.headers.get("TIMEOUT"), initial)
            if not sid:
                self._send(412, "text/plain", "Precondition Failed")
                return
        self._send(200, "text/plain", b"", {
            "SID": sid,
            "TIMEOUT": f"Second-{timeout}",
            "Server": self.server_version,
        })

    def do_UNSUBSCRIBE(self):
        key = self.path.rsplit("/", 1)[-1]
        if not self.path.startswith("/evt/") or key not in SERVICES:
            self._send(404, "text/plain", "Not Found")
            return
        service_name, _ = SERVICES[key]
        ok = self.server.events[service_name].unsubscribe(self.headers.get("SID", ""))
        self._send(200 if ok else 412, "text/plain", b"")


class UPnPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg, renderer, events):
        super().__init__(("0.0.0.0", cfg.port), UPnPHandler)
        self.cfg = cfg
        self.renderer = renderer
        self.events = events

    def initial_state(self, service_name):
        if service_name == "AVTransport":
            return self.renderer.avt_state()
        if service_name == "RenderingControl":
            return self.renderer.rcs_state()
        return {"SourceProtocolInfo": "",
                "SinkProtocolInfo": device.SINK_PROTOCOL_INFO,
                "CurrentConnectionIDs": "0"}
