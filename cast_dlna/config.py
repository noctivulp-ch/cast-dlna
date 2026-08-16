"""Configuración global: argumentos de CLI, identidad del dispositivo y red."""

import argparse
import os
import socket
import uuid

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900
MAX_AGE = 1800


def _default_name():
    return os.uname().nodename or "cast-dlna"


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="cast-dlna",
        description="Renderer DLNA/UPnP completo con mpv como backend",
    )
    ap.add_argument("--name", default=_default_name(),
                    help="Nombre visible en la red (default: hostname)")
    ap.add_argument("--port", type=int, default=8201,
                    help="Puerto HTTP del servidor UPnP (default: 8201)")
    ap.add_argument("--bind", default="",
                    help="IP a anunciar; vacío = autodetectar la de salida")
    ap.add_argument("--mpv", default="mpv", help="Ruta al binario de mpv")
    ap.add_argument("--mpv-args", default="",
                    help="Args extra para mpv, separados por espacios")
    ap.add_argument("--socket", default="",
                    help="Ruta del socket IPC (default: $XDG_RUNTIME_DIR/cast-dlna.sock)")
    ap.add_argument("--fullscreen", action="store_true",
                    help="Abrir cada cast en pantalla completa")
    ap.add_argument("--no-osd", action="store_true",
                    help="Desactivar el OSD de mpv en los comandos remotos")
    ap.add_argument("--ignore-remote-volume", action="store_true",
                    help="Aceptar SetVolume/SetMute del controlador sin aplicarlos: "
                         "el volumen se gestiona solo en este equipo")
    ap.add_argument("--no-live-latency", action="store_true",
                    help="No aplicar el modo de baja latencia a streams en "
                         "directo (MPEG-TS, compartir pantalla)")
    ap.add_argument("--uuid", default="",
                    help="UUID fijo del dispositivo (default: derivado de la MAC)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Log detallado de SOAP/GENA")
    return ap.parse_args(argv)


def outbound_ip():
    """IP de la interfaz por la que sale el tráfico hacia la LAN."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((SSDP_ADDR, 1))
        return s.getsockname()[0]


class Config:
    def __init__(self, args):
        self.args = args
        self.name = args.name
        self.port = args.port
        self.ip = args.bind or outbound_ip()
        self.base_url = f"http://{self.ip}:{self.port}"
        # UDN estable entre arranques: los controladores recuerdan el
        # dispositivo por su UUID, y uno aleatorio crearía una entrada nueva
        # en la lista del móvil cada vez que se reinicia el renderer.
        self.udn = "uuid:" + (args.uuid or str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"cast-dlna.{uuid.getnode():012x}")))
        self.mpv = args.mpv
        self.mpv_args = args.mpv_args.split() if args.mpv_args else []
        self.ipc_socket = args.socket or os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "cast-dlna.sock")
        self.fullscreen = args.fullscreen
        self.osd = not args.no_osd
        self.live_latency = not args.no_live_latency
        self.ignore_remote_volume = args.ignore_remote_volume
        self.verbose = args.verbose

    def log(self, *parts):
        print(*parts, flush=True)

    def debug(self, *parts):
        if self.verbose:
            print(*parts, flush=True)
