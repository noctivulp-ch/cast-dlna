"""Punto de entrada de cast-dlna."""

import atexit
import errno
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

    # El socket HTTP se abre antes de lanzar mpv: si el puerto está ocupado
    # hay que fallar sin dejar un mpv huérfano detrás.
    try:
        server = UPnPServer(cfg, None, events)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            cfg.log(f"[cast-dlna] el puerto {cfg.port} ya está en uso — "
                    f"¿hay otra instancia corriendo?")
            cfg.log(f"[cast-dlna] usa --port <otro> o detén la instancia previa "
                    f"(pkill -f cast-dlna)")
            return 1
        cfg.log(f"[cast-dlna] no se pudo abrir {cfg.ip}:{cfg.port}: {exc}")
        return 1

    renderer_ref = {}
    player = MpvPlayer(cfg, on_change=lambda: renderer_ref["r"].on_player_change()
                       if "r" in renderer_ref else None)
    renderer = Renderer(cfg, player, events)
    renderer_ref["r"] = renderer
    server.renderer = renderer
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
    atexit.register(player.shutdown)

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
