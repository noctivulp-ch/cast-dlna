"""Parseo de metadata DIDL-Lite: título, duración, subtítulos y cabeceras HTTP.

Los controladores no coinciden en cómo declaran los subtítulos: Samsung usa
`sec:CaptionInfo(Ex)`, BubbleUPnP y Web Video Caster usan `pv:subtitleFileUri`
o un `<res>` extra con protocolInfo de texto, y algunos servidores solo lo
exponen en la cabecera `CaptionInfo.sec` de la propia respuesta HTTP. Se
soportan las cuatro vías.
"""

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SUB_MIMES = ("text/srt", "text/vtt", "text/plain", "application/x-subrip",
             "text/x-ssa", "application/x-ssa", "text/ass", "smi/caption",
             "application/ttml+xml", "text/vtt;charset=utf-8")

SUB_EXTS = (".srt", ".vtt", ".ass", ".ssa", ".sub", ".smi", ".ttml", ".dfxp")

FORWARDED_HEADERS = ("referer", "referrer", "user-agent", "cookie",
                     "authorization", "origin", "x-forwarded-for")

# MPEG-TS por HTTP es lo que emiten las funciones de compartir pantalla
# (CastLab entre ellas). Es un stream en directo sin fin ni duración, así que
# el buffering pensado para VOD se traduce en segundos de retraso.
LIVE_MIMES = ("video/mp2t", "video/vnd.dlna.mpeg-tts", "video/mpeg-tts",
              "application/x-mpegurl", "application/vnd.apple.mpegurl")


def _localname(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _attr(elem, name):
    for key, value in elem.attrib.items():
        if _localname(key).lower() == name.lower():
            return value
    return None


def parse_duration(text):
    """'H:MM:SS.mmm' → segundos. Devuelve 0 si no es parseable."""
    if not text:
        return 0.0
    m = re.match(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{2})(?:\.(\d+))?", text)
    if not m:
        return 0.0
    hours, minutes, seconds, frac = m.groups()
    total = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)
    if frac:
        total += float("0." + frac)
    return float(total)


def format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class Media:
    def __init__(self):
        self.title = ""
        self.duration = 0.0
        self.subtitles = []      # [(url, lang)]
        self.headers = {}
        self.mime = ""
        self.live = False
        self.raw = ""

    def __repr__(self):
        return (f"Media(title={self.title!r}, dur={self.duration}, "
                f"subs={len(self.subtitles)}, headers={list(self.headers)}, "
                f"live={self.live})")


def parse_metadata(raw, uri=""):
    """DIDL-Lite (ya des-escapado) → Media."""
    media = Media()
    media.raw = raw or ""
    if not raw or not raw.strip():
        _headers_from_uri(uri, media)
        return media

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        _parse_with_regex(raw, media)
        _headers_from_uri(uri, media)
        return media

    for elem in root.iter():
        name = _localname(elem.tag).lower()
        text = (elem.text or "").strip()

        if name == "title" and text and not media.title:
            media.title = text
        elif name in ("captioninfo", "captioninfoex") and text:
            media.subtitles.append((text, _attr(elem, "type") or ""))
        elif name == "subtitlefileuri" and text:
            media.subtitles.append((text, _attr(elem, "subtitlefiletype") or ""))
        elif name == "res" and text:
            proto = (_attr(elem, "protocolInfo") or "").lower()
            if any(mime in proto for mime in SUB_MIMES) or \
                    text.lower().split("?")[0].endswith(SUB_EXTS):
                media.subtitles.append((text, ""))
            else:
                if not media.mime:
                    parts = proto.split(":")
                    media.mime = parts[2] if len(parts) > 2 else ""
                if not media.duration:
                    media.duration = parse_duration(_attr(elem, "duration"))
                if any(mime in proto for mime in LIVE_MIMES):
                    media.live = True

    _dedup_subs(media)
    _headers_from_uri(uri, media)
    return media


def _parse_with_regex(raw, media):
    m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", raw, re.S)
    if m:
        media.title = m.group(1).strip()
    for pattern in (r"<sec:CaptionInfoE?x?[^>]*>(.*?)</sec:CaptionInfoE?x?>",
                    r"<pv:subtitleFileUri[^>]*>(.*?)</pv:subtitleFileUri>"):
        for hit in re.findall(pattern, raw, re.S):
            if hit.strip():
                media.subtitles.append((hit.strip(), ""))
    _dedup_subs(media)


def _dedup_subs(media):
    seen = set()
    unique = []
    for url, lang in media.subtitles:
        if url and url not in seen and url.startswith(("http://", "https://", "file://", "/")):
            seen.add(url)
            unique.append((url, lang))
    media.subtitles = unique


def _headers_from_uri(uri, media):
    """Algunos controladores empujan la cabecera dentro del query string."""
    for key in ("referer", "referrer"):
        m = re.search(rf"[?&]{key}=([^&]+)", uri, re.I)
        if m:
            media.headers.setdefault("Referer", urllib.parse.unquote(m.group(1)))
    if "Referer" not in media.headers and uri.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(uri)
        media.headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"


def probe_caption_header(uri, timeout=3.0):
    """HEAD al recurso para leer `CaptionInfo.sec` — algunos servidores solo lo
    exponen ahí. Falla en silencio: es una vía opcional del estándar."""
    try:
        req = urllib.request.Request(uri, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for key in ("CaptionInfo.sec", "CaptionInfo", "Captioninfo.sec"):
                value = resp.headers.get(key)
                if value:
                    return value.strip()
    except Exception:
        pass
    return ""
