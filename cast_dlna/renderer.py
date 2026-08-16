"""Implementación de las acciones de AVTransport, RenderingControl y
ConnectionManager sobre el backend mpv."""

import threading
import time
import urllib.parse

from . import device, didl, soap

SEEK_MODES = ("REL_TIME", "ABS_TIME", "TRACK_NR", "REL_COUNT", "ABS_COUNT")


class Renderer:
    def __init__(self, cfg, player, events):
        self.cfg = cfg
        self.player = player
        self.events = events           # {"AVTransport": EventManager, ...}
        self.lock = threading.Lock()
        self.uri = ""
        self.uri_metadata = ""
        self.next_uri = ""
        self.next_metadata = ""
        self.media = didl.Media()
        self.play_mode = "NORMAL"
        self.status = "OK"
        self.screen_share = False
        self._last_avt = {}
        self._last_rcs = {}
        threading.Thread(target=self._ticker, daemon=True).start()

    # ── Estado publicado por GENA ──────────────────────────────────────────
    def avt_state(self):
        state = self.player.transport_state
        return {
            "TransportState": state,
            "TransportStatus": self.status,
            "CurrentPlayMode": self.play_mode,
            "TransportPlaySpeed": "1",
            "NumberOfTracks": max(1, self.player.playlist_count) if self.uri else 0,
            "CurrentTrack": self.player.playlist_pos + 1 if self.uri else 0,
            "CurrentTrackDuration": self._duration_str(),
            "CurrentMediaDuration": self._duration_str(),
            "CurrentTrackURI": self.uri,
            "CurrentTrackMetaData": self.uri_metadata,
            "AVTransportURI": self.uri,
            "AVTransportURIMetaData": self.uri_metadata,
            "NextAVTransportURI": self.next_uri,
            "NextAVTransportURIMetaData": self.next_metadata,
            "PlaybackStorageMedium": "NETWORK" if self.uri else "NONE",
            "RecordStorageMedium": "NOT_IMPLEMENTED",
            "RecordMediumWriteStatus": "NOT_IMPLEMENTED",
            "CurrentRecordQualityMode": "NOT_IMPLEMENTED",
            "PossibleRecordQualityModes": "NOT_IMPLEMENTED",
            "CurrentTransportActions": self._transport_actions(),
            "RelativeTimePosition": self._position_str(),
            "AbsoluteTimePosition": self._position_str(),
        }

    def rcs_state(self):
        return {
            "Volume": self.player.volume,
            "Mute": 1 if self.player.muted else 0,
            "PresetNameList": "FactoryDefaults",
        }

    def on_player_change(self):
        self._publish("AVTransport", self.avt_state(), self._last_avt)
        self._publish("RenderingControl", self.rcs_state(), self._last_rcs)

    def _publish(self, service, state, cache):
        delta = {k: v for k, v in state.items() if cache.get(k) != v}
        cache.update(state)
        if delta:
            self.events[service].publish(delta)

    def _ticker(self):
        """Refresco periódico: la posición no genera property-change útil para
        el controlador si solo se publica al cambiar de estado."""
        while True:
            time.sleep(1)
            if self.player.transport_state in ("PLAYING", "TRANSITIONING"):
                self.on_player_change()

    # ── Formateo ───────────────────────────────────────────────────────────
    def _duration_str(self):
        seconds = self.player.duration or self.media.duration
        return didl.format_duration(seconds) if seconds else "00:00:00"

    def _position_str(self):
        return didl.format_duration(self.player.position)

    def _transport_actions(self):
        state = self.player.transport_state
        actions = ["Play", "Stop", "Seek", "X_DLNA_SeekTime"]
        if state == "PLAYING":
            actions.append("Pause")
        if state in ("PAUSED_PLAYBACK", "STOPPED", "NO_MEDIA_PRESENT"):
            actions.append("Play")
        if self.player.playlist_count > 1:
            actions += ["Next", "Previous"]
        return ",".join(dict.fromkeys(actions))

    # ── AVTransport ────────────────────────────────────────────────────────
    def avt(self, action, args, client_ip=None):
        if action == "SetAVTransportURI":
            self._client_ip = client_ip
        handler = getattr(self, "_avt_" + action, None)
        if handler is None:
            return None
        return handler(args)

    def _avt_SetAVTransportURI(self, args):
        uri = soap.unescape(args.get("CurrentURI", "")).strip()
        raw_meta = soap.unescape(args.get("CurrentURIMetaData", "")).strip()
        if not uri:
            self.stop_and_clear()
            return {}

        media = didl.parse_metadata(raw_meta, uri)
        if not media.subtitles:
            caption = didl.probe_caption_header(uri)
            if caption:
                media.subtitles.append((caption, ""))

        with self.lock:
            self.uri = uri
            self.uri_metadata = args.get("CurrentURIMetaData", "")
            self.media = media
            self.status = "OK"
            self.screen_share = self._is_screen_share(uri, media)

        self.cfg.log(f"▶  {media.title or '(sin título)'}")
        self.cfg.log(f"   {uri[:110]}{'…' if len(uri) > 110 else ''}")
        if media.subtitles:
            self.cfg.log(f"   subs: {[s[0][:60] for s in media.subtitles]}")
        if media.headers:
            self.cfg.debug(f"   hdrs: {media.headers}")

        self.player.load(uri, headers=media.headers, subtitles=media.subtitles,
                         title=media.title, live=media.live)
        self.on_player_change()
        return {}

    def _is_screen_share(self, uri, media):
        """Compartir pantalla es el controlador sirviéndose a sí mismo un
        MPEG-TS en directo. Hacen falta las dos señales: por MIME sola se
        confundiría con IPTV, y por origen sola con el proxy local que monta
        Web Video Caster para servir un mp4 desde el propio teléfono."""
        if not media.live:
            return False
        host = urllib.parse.urlparse(uri).hostname
        return bool(host) and host == getattr(self, "_client_ip", None)

    def _volume_is_remote(self):
        mode = self.cfg.remote_volume
        if mode == "always":
            return True
        if mode == "never":
            return False
        return not self.screen_share

    def _avt_SetNextAVTransportURI(self, args):
        uri = soap.unescape(args.get("NextURI", "")).strip()
        with self.lock:
            self.next_uri = uri
            self.next_metadata = args.get("NextURIMetaData", "")
        if uri:
            media = didl.parse_metadata(
                soap.unescape(self.next_metadata), uri)
            self.player.load(uri, headers=media.headers, append=True)
            self.cfg.log(f"⏭  siguiente: {uri[:80]}")
        self.on_player_change()
        return {}

    def _avt_GetMediaInfo(self, args):
        return {
            "NrTracks": max(1, self.player.playlist_count) if self.uri else 0,
            "MediaDuration": self._duration_str(),
            "CurrentURI": self.uri,
            "CurrentURIMetaData": self.uri_metadata,
            "NextURI": self.next_uri,
            "NextURIMetaData": self.next_metadata,
            "PlayMedium": "NETWORK" if self.uri else "NONE",
            "RecordMedium": "NOT_IMPLEMENTED",
            "WriteStatus": "NOT_IMPLEMENTED",
        }

    def _avt_GetMediaInfo_Ext(self, args):
        info = self._avt_GetMediaInfo(args)
        category = "NO_MEDIA" if not self.uri else (
            "TRACK_UNAWARE" if not self.player.seekable else "TRACK_AWARE")
        return {"CurrentType": category, **info}

    def _avt_GetTransportInfo(self, args):
        return {
            "CurrentTransportState": self.player.transport_state,
            "CurrentTransportStatus": self.status,
            "CurrentSpeed": "1",
        }

    def _avt_GetPositionInfo(self, args):
        return {
            "Track": self.player.playlist_pos + 1 if self.uri else 0,
            "TrackDuration": self._duration_str(),
            "TrackMetaData": self.uri_metadata,
            "TrackURI": self.uri,
            "RelTime": self._position_str(),
            "AbsTime": self._position_str(),
            "RelCount": int(self.player.position) or 2147483647,
            "AbsCount": int(self.player.position) or 2147483647,
        }

    def _avt_GetDeviceCapabilities(self, args):
        return {
            "PlayMedia": "NONE,NETWORK,HDD,UNKNOWN",
            "RecMedia": "NOT_IMPLEMENTED",
            "RecQualityModes": "NOT_IMPLEMENTED",
        }

    def _avt_GetTransportSettings(self, args):
        return {"PlayMode": self.play_mode, "RecQualityMode": "NOT_IMPLEMENTED"}

    def _avt_GetCurrentTransportActions(self, args):
        return {"Actions": self._transport_actions()}

    def _avt_X_DLNA_GetBytePositionInfo(self, args):
        return {"TrackSize": "0", "RelByte": "0", "AbsByte": "0"}

    def _avt_Play(self, args):
        speed = args.get("Speed", "1")
        if speed not in ("1", "1.0", ""):
            self.player.set_speed(float(speed))
        if self.player.transport_state in ("STOPPED", "NO_MEDIA_PRESENT") and self.uri:
            self.player.load(self.uri, headers=self.media.headers,
                             subtitles=self.media.subtitles,
                             title=self.media.title, live=self.media.live)
        else:
            self.player.play()
        self.cfg.log("▶  play")
        return {}

    def _avt_Pause(self, args):
        self.player.pause()
        self.cfg.log("⏸  pause")
        return {}

    def _avt_Stop(self, args):
        self.player.stop()
        self.cfg.log("⏹  stop")
        self.on_player_change()
        return {}

    def _avt_Seek(self, args):
        unit = (args.get("Unit") or "REL_TIME").upper()
        target = (args.get("Target") or "").strip()
        if unit not in SEEK_MODES:
            raise UPnPFault(710)
        if unit in ("REL_TIME", "ABS_TIME"):
            seconds = didl.parse_duration(target)
            if not seconds and not target.startswith(("0:00:00", "00:00:00", "0")):
                raise UPnPFault(711)
            self.player.seek(seconds)
            self.cfg.log(f"⏩ seek → {didl.format_duration(seconds)}")
        elif unit == "TRACK_NR":
            try:
                index = max(0, int(target) - 1)
            except ValueError:
                raise UPnPFault(711)
            self.player.command("set_property", "playlist-pos", index)
        else:
            raise UPnPFault(710)
        self.on_player_change()
        return {}

    def _avt_Next(self, args):
        self.player.next_track()
        return {}

    def _avt_Previous(self, args):
        self.player.prev_track()
        return {}

    def _avt_SetPlayMode(self, args):
        mode = (args.get("NewPlayMode") or "NORMAL").upper()
        if mode not in ("NORMAL", "REPEAT_ONE", "REPEAT_ALL", "SHUFFLE", "RANDOM"):
            raise UPnPFault(712, "Play mode not supported")
        self.play_mode = mode
        self.player.set_play_mode(mode)
        self.on_player_change()
        return {}

    def stop_and_clear(self):
        with self.lock:
            self.uri = ""
            self.uri_metadata = ""
            self.next_uri = ""
            self.next_metadata = ""
            self.media = didl.Media()
        self.player.stop()
        self.on_player_change()

    # ── RenderingControl ───────────────────────────────────────────────────
    def rcs(self, action, args):
        handler = getattr(self, "_rcs_" + action, None)
        if handler is None:
            return None
        return handler(args)

    def _rcs_ListPresets(self, args):
        return {"CurrentPresetNameList": "FactoryDefaults"}

    def _rcs_SelectPreset(self, args):
        if (args.get("PresetName") or "") == "FactoryDefaults":
            self.player.set_volume(100)
            self.player.set_mute(False)
        return {}

    def _rcs_GetVolume(self, args):
        return {"CurrentVolume": self.player.volume}

    def _rcs_SetVolume(self, args):
        try:
            level = int(args.get("DesiredVolume", "0"))
        except ValueError:
            raise UPnPFault(600)
        if not 0 <= level <= 100:
            raise UPnPFault(601, "Argument Value Out of Range")
        # Rechazar la acción haría que el controlador diese el renderer por
        # roto, así que se acepta y se descarta. GetVolume sigue devolviendo el
        # valor real de mpv: el slider del controlador saltará de vuelta, que
        # es preferible a mentir sobre el estado del reproductor.
        if not self._volume_is_remote():
            self.cfg.log(f"🔇 SetVolume({level}) ignorado ({self._volume_reason()})")
            return {}
        self.player.set_volume(level)
        self.cfg.log(f"🔊 volumen → {level}")
        return {}

    def _volume_reason(self):
        return ("compartir pantalla" if self.screen_share
                else f"--remote-volume {self.cfg.remote_volume}")

    def _rcs_GetVolumeDB(self, args):
        return {"CurrentVolume": _to_db(self.player.volume)}

    def _rcs_SetVolumeDB(self, args):
        try:
            db = int(args.get("DesiredVolume", "0"))
        except ValueError:
            raise UPnPFault(600)
        self.player.set_volume(_from_db(db))
        return {}

    def _rcs_GetVolumeDBRange(self, args):
        return {"MinValue": -10240, "MaxValue": 0}

    def _rcs_GetMute(self, args):
        return {"CurrentMute": 1 if self.player.muted else 0}

    def _rcs_SetMute(self, args):
        desired = (args.get("DesiredMute") or "0").strip().lower()
        if not self._volume_is_remote():
            self.cfg.log(f"🔇 SetMute({desired}) ignorado ({self._volume_reason()})")
            return {}
        self.player.set_mute(desired in ("1", "true", "yes"))
        return {}

    # ── ConnectionManager ──────────────────────────────────────────────────
    def cms(self, action, args):
        if action == "GetProtocolInfo":
            return {"Source": "", "Sink": device.SINK_PROTOCOL_INFO}
        if action == "GetCurrentConnectionIDs":
            return {"ConnectionIDs": "0"}
        if action == "GetCurrentConnectionInfo":
            return {
                "RcsID": 0,
                "AVTransportID": 0,
                "ProtocolInfo": "http-get:*:*:*",
                "PeerConnectionManager": "",
                "PeerConnectionID": -1,
                "Direction": "Input",
                "Status": "OK",
            }
        return None


class UPnPFault(Exception):
    def __init__(self, code, description=""):
        super().__init__(description or soap.ERRORS.get(code, "Action Failed"))
        self.code = code
        self.description = description or soap.ERRORS.get(code, "Action Failed")


def _to_db(volume):
    """0-100 → centibelios. mpv es lineal; la conversión es aproximada pero
    monótona, que es lo único que los controladores usan del rango."""
    if volume <= 0:
        return -10240
    return int(round(2000 * (volume / 100.0 - 1)))


def _from_db(db):
    return max(0, min(100, int(round((db / 2000.0 + 1) * 100))))
