"""Punto de entrada de cast-dlna."""

import signal
import sys
import threading

from .config import Config, parse_args
from .gena import EventManager
from .player import MpvPlayer
from .renderer import Renderer
from .server import UPnPServer
from .ssdp import SSDP


def main(argv=None):
    cfg = Config(parse_args(argv))

    events = {name: EventManager(cfg, name)
              for name in ("AVTransport", "RenderingControl", "ConnectionManager")}

    renderer_ref = {}
    player = MpvPlayer(cfg, on_change=lambda: renderer_ref["r"].on_player_change()
                       if "r" in renderer_ref else None)
    renderer = Renderer(cfg, player, events)
    renderer_ref["r"] = renderer

    server = UPnPServer(cfg, renderer, events)
    ssdp = SSDP(cfg)

    stopping = threading.Event()

    def shutdown(signum=None, frame=None):
        if stopping.is_set():
            return
        stopping.set()
        cfg.log("\n[cast-dlna] apagando…")
        ssdp.stop()
        player.shutdown()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    ssdp.start()

    cfg.log(f"[cast-dlna] {cfg.name} en {cfg.base_url}")
    cfg.log(f"[cast-dlna] UDN: {cfg.udn}")
    cfg.log(f"[cast-dlna] IPC mpv: {cfg.ipc_socket}")
    cfg.log("[cast-dlna] listo — esperando cast (Ctrl+C para salir)")

    try:
        stopping.wait()
    except KeyboardInterrupt:
        shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
