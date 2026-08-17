"""Backend mpv: un único proceso persistente en modo idle, controlado por IPC JSON.

Mantener mpv vivo entre casts es lo que permite implementar de verdad Seek,
Pause, volumen, posición y eventos: si se relanzase el proceso por cada URI el
socket IPC se perdería y el renderer solo podría reproducir y matar.
"""

import json
import os
import socket
import subprocess
import threading
import time

OBSERVED = [
    "pause", "time-pos", "duration", "core-idle", "eof-reached",
    "volume", "mute", "path", "media-title", "seekable", "untimed",
    "playlist-count", "playlist-pos", "idle-active", "speed", "track-list",
    "demuxer-cache-duration",
]



# Propiedades que toca el modo de baja latencia; se guardan al arrancar mpv
# para poder restaurar el comportamiento normal al volver a un vídeo VOD.
LATENCY_PROPS = [
    "audio-buffer", "vd-lavc-threads", "cache-pause", "demuxer-lavf-o",
    "demuxer-lavf-probe-info", "demuxer-lavf-analyzeduration", "video-sync",
    "interpolation", "video-latency-hacks", "stream-buffer-size",
    "cache", "demuxer-readahead-secs", "cache-secs",
]


class MpvPlayer:
    def __init__(self, cfg, on_change=None):
        self.cfg = cfg
        self.on_change = on_change or (lambda: None)
        self._proc = None
        self._sock = None
        self._req_id = 0
        self._pending = {}
        self._lock = threading.Lock()
        self._props = {}
        self._pending_subs = []
        self._pending_start = 0.0
        self._stopped = False         # STOPPED explícito vs. NO_MEDIA_PRESENT
        self._has_media = False
        self._running = True
        self._transitioning = False
        self._live = False
        self._image = False
        self._untimed_forzado = False
        self._low_latency = False
        self._vod_defaults = {}
        threading.Thread(target=self._supervisor, daemon=True).start()

    # ── Ciclo de vida del proceso ──────────────────────────────────────────
    def _spawn(self):
        try:
            os.unlink(self.cfg.ipc_socket)
        except FileNotFoundError:
            pass
        cmd = [
            self.cfg.mpv,
            "--idle=yes",
            "--force-window=no",
            "--no-terminal",
            "--keep-open=no",
            f"--input-ipc-server={self.cfg.ipc_socket}",
            f"--title=cast-dlna — {self.cfg.name}",
        ] + self.cfg.mpv_args
        self.cfg.log(f"[mpv] lanzando: {' '.join(cmd)}")
        self._proc = subprocess.Popen(
            cmd, env=os.environ.copy(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _supervisor(self):
        while self._running:
            if self._proc is None or self._proc.poll() is not None:
                self._has_media = False
                self._props.clear()
                self._spawn()
                if self._connect():
                    threading.Thread(target=self._reader, daemon=True).start()
                    self._bootstrap()
            time.sleep(1)

    def _connect(self):
        for _ in range(50):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(self.cfg.ipc_socket)
                self._sock = s
                return True
            except OSError:
                time.sleep(0.1)
        self.cfg.log("[mpv] no se pudo abrir el socket IPC")
        return False

    def _bootstrap(self):
        for i, prop in enumerate(OBSERVED, start=1):
            self._send({"command": ["observe_property", i, prop]})
        self._low_latency = False
        self._image_duration_default = self.get_property("image-display-duration") or 5
        self._snapshot_latency_defaults()

    # ── Transporte IPC ─────────────────────────────────────────────────────
    def _send(self, payload, wait=False, timeout=1.5):
        with self._lock:
            sock = self._sock
            if sock is None:
                return None
            self._req_id += 1
            rid = self._req_id
            payload = dict(payload, request_id=rid)
            ev = threading.Event() if wait else None
            if wait:
                self._pending[rid] = [ev, None]
            try:
                sock.sendall((json.dumps(payload) + "\n").encode())
            except OSError:
                self._pending.pop(rid, None)
                self._sock = None
                return None
        if not wait:
            return None
        ev.wait(timeout)
        with self._lock:
            entry = self._pending.pop(rid, None)
        return entry[1] if entry else None

    def command(self, *args, wait=False):
        return self._send({"command": list(args)}, wait=wait)

    def set_property(self, name, value):
        return self.command("set_property", name, value)

    def get_property(self, name, timeout=1.5):
        reply = self._send({"command": ["get_property", name]},
                           wait=True, timeout=timeout)
        if reply and reply.get("error") == "success":
            return reply.get("data")
        return None

    def _reader(self):
        buf = b""
        sock = self._sock
        while self._running and sock is not None:
            try:
                chunk = sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line.decode(errors="replace"))
                except ValueError:
                    continue
                self._dispatch(msg)
        with self._lock:
            if self._sock is sock:
                self._sock = None

    def _dispatch(self, msg):
        rid = msg.get("request_id")
        if rid is not None and "error" in msg:
            with self._lock:
                entry = self._pending.get(rid)
                if entry:
                    entry[1] = msg
                    entry[0].set()
            return
        event = msg.get("event")
        if event == "property-change":
            self._props[msg.get("name")] = msg.get("data")
            if msg.get("name") == "track-list":
                self._revisar_untimed(msg.get("data"))
            if msg.get("name") in ("pause", "core-idle", "idle-active",
                                   "duration", "volume", "mute", "path"):
                self.on_change()
        elif event == "file-loaded":
            self._transitioning = False
            self._has_media = True
            self._stopped = False
            if self._live and self.cfg.live_latency:
                self._apply_untimed_if_silent()
            self._apply_pending_subs()
            if self._pending_start:
                self.command("seek", self._pending_start, "absolute")
                self._pending_start = 0.0
            if self.cfg.fullscreen:
                self.set_property("fullscreen", True)
            self.on_change()
        elif event in ("end-file", "idle"):
            self._transitioning = False
            self.on_change()
        elif event == "start-file":
            self._transitioning = True

    def _apply_pending_subs(self):
        for url, lang in self._pending_subs:
            self.command("sub-add", url, "select", lang or "sub")
        self._pending_subs = []

    # ── Baja latencia para streams en directo ──────────────────────────────
    def _snapshot_latency_defaults(self):
        """Guarda los valores de fábrica para poder volver a modo VOD."""
        self._vod_defaults = {}
        for prop in LATENCY_PROPS:
            value = self.get_property(prop)
            if value is not None:
                self._vod_defaults[prop] = value

    def set_low_latency(self, enabled):
        """El perfil low-latency de mpv desactiva caché y readahead y recorta
        el análisis del demuxer. En VOD costaría robustez, pero en un stream
        en directo esos búferes son puro retraso.

        El precio es que el retraso que acumula la diferencia entre el reloj
        del emisor y el de este equipo se queda en el búfer del socket, donde
        no se puede ni medir ni consumir. Se probó a darle caché para poder
        verlo y corregirlo con la velocidad de reproducción, y salió peor:
        ver el apartado del retraso en directo del `README.md`.
        """
        if enabled == self._low_latency:
            return
        if enabled:
            self.command("apply-profile", "low-latency")
            self.set_property("cache", "no")
            self.set_property("demuxer-readahead-secs", 0)
            self.set_property("cache-secs", 0)
        else:
            for prop, value in self._vod_defaults.items():
                self.set_property(prop, value)
            self.set_property("untimed", False)
            self._untimed_forzado = False
        self._low_latency = enabled
        self.cfg.log(f"[mpv] baja latencia {'activada' if enabled else 'desactivada'}")

    def _apply_untimed_if_silent(self):
        """Sin pista de audio mpv no tiene reloj al que engancharse y el
        desfase con los timestamps del emisor se acumula. `untimed` muestra
        cada cuadro en cuanto llega, que es lo que se quiere al compartir
        pantalla — y por eso solo se activa si de verdad no hay audio."""
        # Se lee del estado observado, nunca con get_property: esto corre en
        # el hilo lector, y esperar ahí una respuesta que solo ese mismo hilo
        # puede procesar lo bloquea hasta que vence el temporizador.
        tracks = self._props.get("track-list") or []
        if not any(t.get("type") == "audio" for t in tracks):
            self.set_property("untimed", True)
            self._untimed_forzado = True
            self.cfg.log("[mpv] stream sin audio → untimed (latencia mínima)")

    def _revisar_untimed(self, tracks):
        """En un MPEG-TS la pista de audio no aparece hasta que llega su
        primer paquete, casi siempre después de `file-loaded`. Si se decidió
        allí, `untimed` acaba puesto sobre un stream que sí tiene audio: mpv
        deja de regirse por el reloj de la pista y la sincronía queda al azar.
        Se retira en cuanto el audio aparece."""
        # La condición se lleva en una bandera propia, no en el estado
        # observado: el aviso de `track-list` con la pista de audio suele
        # adelantar al de `untimed`, y consultar ese estado dejaba el modo
        # puesto para siempre sobre un stream que sí tenía audio.
        if not self._untimed_forzado:
            return
        if any(t.get("type") == "audio" for t in (tracks or [])):
            self.set_property("untimed", False)
            self._untimed_forzado = False
            self.cfg.log("[mpv] apareció pista de audio → untimed desactivado")

    # ── API de reproducción ────────────────────────────────────────────────
    def load(self, uri, headers=None, subtitles=None, title=None,
             append=False, start=0.0, live=False, image=False):
        if not append:
            self._transitioning = True
            self._pending_subs = list(subtitles or [])
            self._pending_start = start
            self._live = live
            self._image = image
            self._untimed_forzado = False
            # Una imagen dura `image-display-duration` (5 s por defecto) y
            # después mpv vuelve a idle y la ventana se cierra. Un cast de una
            # foto tiene que quedarse hasta que el controlador mande otra cosa.
            self.set_property("image-display-duration",
                              "inf" if image else self._image_duration_default)
            self.set_low_latency(live and self.cfg.live_latency)
            self._apply_headers(headers or {})
            if title:
                self.set_property("force-media-title", title)
            else:
                self.set_property("force-media-title", "")
        self.command("loadfile", uri, "append" if append else "replace")
        if not append:
            self.set_property("pause", False)
        self.on_change()

    def _apply_headers(self, headers):
        fields = []
        for key, value in headers.items():
            low = key.lower()
            if low == "referer":
                self.set_property("referrer", value)
            elif low == "user-agent":
                self.set_property("user-agent", value)
            else:
                fields.append(f"{key}: {value}")
        self.set_property("http-header-fields", fields)

    def play(self):
        if self._has_media:
            self.set_property("pause", False)
        self.on_change()

    def pause(self):
        self.set_property("pause", True)
        self.on_change()

    def toggle_pause(self):
        self.set_property("pause", not bool(self._props.get("pause")))
        self.on_change()

    def stop(self):
        self.command("stop")
        self._has_media = False
        self._stopped = True
        self._props["path"] = None
        self.on_change()

    def seek(self, seconds):
        self.command("seek", float(seconds), "absolute")
        self.on_change()

    def seek_relative(self, delta):
        self.command("seek", float(delta), "relative")

    def next_track(self):
        self.command("playlist-next", "weak")
        self.on_change()

    def prev_track(self):
        self.command("playlist-prev", "weak")
        self.on_change()

    def set_volume(self, level):
        self.set_property("volume", max(0, min(100, int(level))))
        self.on_change()

    def set_mute(self, muted):
        self.set_property("mute", bool(muted))
        self.on_change()

    def set_speed(self, speed):
        self.set_property("speed", float(speed))

    def set_play_mode(self, mode):
        loop = "inf" if mode in ("REPEAT_ONE", "REPEAT_ALL") else "no"
        self.set_property("loop-file" if mode == "REPEAT_ONE" else "loop-playlist", loop)
        self.set_property("shuffle", mode in ("SHUFFLE", "RANDOM"))

    # ── Estado ─────────────────────────────────────────────────────────────
    @property
    def position(self):
        return float(self._props.get("time-pos") or 0.0)

    @property
    def duration(self):
        return float(self._props.get("duration") or 0.0)

    @property
    def volume(self):
        return int(self._props.get("volume") or 0)

    @property
    def muted(self):
        return bool(self._props.get("mute"))

    @property
    def seekable(self):
        return bool(self._props.get("seekable"))

    @property
    def playlist_count(self):
        return int(self._props.get("playlist-count") or 0)

    @property
    def playlist_pos(self):
        return int(self._props.get("playlist-pos") or 0)

    @property
    def transport_state(self):
        if self._transitioning:
            return "TRANSITIONING"
        if not self._has_media or self._props.get("idle-active"):
            return "STOPPED" if self._stopped else "NO_MEDIA_PRESENT"
        if self._props.get("pause"):
            return "PAUSED_PLAYBACK"
        if self._image:
            return "PLAYING"
        if self._props.get("core-idle"):
            return "TRANSITIONING"
        return "PLAYING"

    def shutdown(self):
        self._running = False
        self.command("quit")
        time.sleep(0.2)
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
