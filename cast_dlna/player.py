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

# Regulación del retraso en directo. El objetivo es el atraso que se acepta a
# cambio de no quedarse sin datos; por encima se reproduce más rápido hasta
# reabsorberlo, con el mismo esquema que el control de velocidad para directos
# de ExoPlayer.
# El colchón objetivo no es cero a propósito: vaciarlo deja al reproductor sin
# datos en cuanto la red o el emisor dan un tirón, y un corte de audio suena
# mucho peor que medio segundo de retraso.
LIVE_BUFFER_OBJETIVO = 0.55   # colchón que se intenta mantener
LIVE_BUFFER_MINIMO = 0.30     # por debajo se deja de acelerar y se recupera
LIVE_SPEED_MAX = 1.04         # techo de velocidad
LIVE_SPEED_MIN = 0.97         # suelo, para rehacer colchón sin que se note
LIVE_ESCALA = 0.5             # exceso, en segundos, que lleva al techo
LIVE_SUAVIZADO = 0.03         # peso de cada lectura en la media del colchón
LIVE_RAMPA = 0.008            # tope de cambio de velocidad por vuelta
LIVE_REGULA_CADA = 0.5        # cada cuánto se revisa
LIVE_READAHEAD = 5            # lectura por delante: saca el atraso del socket
# Saltar a lo último recibido vacía el búfer de golpe —el seek hace flush del
# demuxer, no avanza dentro de lo ya leído—, y con el búfer seco el sonido se
# rompe. Queda solo como último recurso ante un atraso enorme y sostenido, no
# como herramienta de ajuste fino.
LIVE_SALTO = 3.0

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
        self._speed_directo = 1.0
        self._colchon_medio = None
        self._vod_defaults = {}
        threading.Thread(target=self._supervisor, daemon=True).start()
        threading.Thread(target=self._regular_directo, daemon=True).start()

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
        """El perfil low-latency de mpv recorta el análisis del demuxer y los
        búferes de salida, que en un directo son puro retraso.

        Lo que no se hereda del perfil es su `cache=no`. Sin caché el retraso
        que se acumula por la diferencia entre el reloj del emisor y el de
        este equipo no desaparece: se queda en el búfer del socket, donde no
        se puede ni medir ni drenar, y crece sin techo. Con caché el atraso se
        hace visible en `demuxer-cache-duration` y [_regular_directo] puede
        reabsorberlo.
        """
        if enabled == self._low_latency:
            return
        if enabled:
            self.command("apply-profile", "low-latency")
            self.set_property("cache", "yes")
            self.set_property("demuxer-readahead-secs", LIVE_READAHEAD)
            self.set_property("cache-secs", LIVE_READAHEAD)
        else:
            for prop, value in self._vod_defaults.items():
                self.set_property(prop, value)
            self.set_property("untimed", False)
            self._untimed_forzado = False
            self.set_property("speed", 1.0)
            self._speed_directo = 1.0
        self._low_latency = enabled
        self.cfg.log(f"[mpv] baja latencia {'activada' if enabled else 'desactivada'}")

    # ── Regulador de retraso en directo ────────────────────────────────────
    def velocidad_para(self, buffer_segundos):
        """Velocidad de reproducción que corresponde a un atraso dado.

        Mismo principio que el `LivePlaybackSpeedControl` de ExoPlayer, que es
        lo que usará la versión de Android TV: en vez de dar saltos, se
        reproduce un poco más rápido hasta volver al retraso objetivo.

        La curva es un smoothstep, no una recta: sale del reposo y llega al
        techo con pendiente nula, así que ni el momento en que empieza a
        corregir ni aquel en que deja de hacerlo tienen una costura audible.
        Una recta acelera de golpe justo al cruzar el objetivo, que es donde
        más se nota.
        """
        if buffer_segundos < LIVE_BUFFER_MINIMO:
            # Sin colchón, el reproductor se queda seco: el audio se entrecorta
            # y la imagen se va. Se frena para rehacerlo, tanto más cuanto más
            # vacío esté, y con la misma curva suave que del otro lado para que
            # tampoco se note el momento en que empieza a frenar.
            t = max(0.0, buffer_segundos) / LIVE_BUFFER_MINIMO
            return LIVE_SPEED_MIN + (1.0 - LIVE_SPEED_MIN) * t * t * (3 - 2 * t)
        exceso = buffer_segundos - LIVE_BUFFER_OBJETIVO
        if exceso <= 0:
            return 1.0
        t = min(1.0, exceso / LIVE_ESCALA)
        return 1.0 + (LIVE_SPEED_MAX - 1.0) * t * t * (3 - 2 * t)

    def _regular_directo(self):
        while self._running:
            time.sleep(LIVE_REGULA_CADA)
            if not (self._live and self.cfg.live_latency and self._has_media):
                continue
            buffer = self._props.get("demuxer-cache-duration")
            if buffer is None:
                continue
            # El colchón instantáneo es puro ruido: el emisor entrega a
            # ráfagas y una sola lectura pasa de 0,0 a 1,1 s entre vueltas.
            # Corregir sobre ese valor persigue el ruido y hace oscilar el
            # sistema; se regula sobre la media, como hace scrcpy.
            actual = float(buffer)
            if self._colchon_medio is None:
                self._colchon_medio = actual
            else:
                self._colchon_medio += (actual - self._colchon_medio) * LIVE_SUAVIZADO
            buffer = self._colchon_medio

            if buffer > LIVE_SALTO:
                salto = buffer - LIVE_BUFFER_OBJETIVO
                self.command("seek", round(salto, 2), "relative")
                if self._speed_directo != 1.0:
                    self.set_property("speed", 1.0)
                    self._speed_directo = 1.0
                self.cfg.log(f"[mpv] atraso de {buffer:.2f}s → salto al directo")
                continue

            objetivo = self.velocidad_para(buffer)
            # Se llega al valor por una rampa, no de un salto: pasar de golpe
            # de la velocidad normal a la corregida se oye como un tirón.
            delta = objetivo - self._speed_directo
            if abs(delta) < 0.0005:
                continue
            # Tope holgado, solo para recortar un pico suelto. La versión
            # anterior lo tenía tan apretado que la velocidad tardaba diez
            # segundos en cruzar su rango: se veía frenando con el búfer lleno
            # porque seguía viniendo de un mínimo anterior, y el lazo oscilaba.
            if abs(delta) > LIVE_RAMPA:
                objetivo = self._speed_directo + (LIVE_RAMPA if delta > 0 else -LIVE_RAMPA)
            self.set_property("speed", round(objetivo, 4))
            self._speed_directo = objetivo
            self.cfg.debug(f"[mpv] colchón {actual:.2f}s (media {buffer:.2f}s)"
                           f" → velocidad {objetivo:.4f}")

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
            self._speed_directo = 1.0
            self._colchon_medio = None
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
