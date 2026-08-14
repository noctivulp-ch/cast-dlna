"""Descriptores UPnP: device.xml y los SCPD de los tres servicios.

Los SCPD se generan desde tablas compactas en vez de escribirse a mano: la
lista de acciones es también la fuente de verdad de lo que el renderer
anuncia, así que declaración e implementación no pueden divergir en silencio.
"""

AVT = "urn:schemas-upnp-org:service:AVTransport:1"
RCS = "urn:schemas-upnp-org:service:RenderingControl:1"
CMS = "urn:schemas-upnp-org:service:ConnectionManager:1"

IN, OUT = "in", "out"

# ── AVTransport ────────────────────────────────────────────────────────────
AVT_ACTIONS = {
    "SetAVTransportURI": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("CurrentURI", IN, "AVTransportURI"),
        ("CurrentURIMetaData", IN, "AVTransportURIMetaData"),
    ],
    "SetNextAVTransportURI": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("NextURI", IN, "NextAVTransportURI"),
        ("NextURIMetaData", IN, "NextAVTransportURIMetaData"),
    ],
    "GetMediaInfo": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("NrTracks", OUT, "NumberOfTracks"),
        ("MediaDuration", OUT, "CurrentMediaDuration"),
        ("CurrentURI", OUT, "AVTransportURI"),
        ("CurrentURIMetaData", OUT, "AVTransportURIMetaData"),
        ("NextURI", OUT, "NextAVTransportURI"),
        ("NextURIMetaData", OUT, "NextAVTransportURIMetaData"),
        ("PlayMedium", OUT, "PlaybackStorageMedium"),
        ("RecordMedium", OUT, "RecordStorageMedium"),
        ("WriteStatus", OUT, "RecordMediumWriteStatus"),
    ],
    "GetMediaInfo_Ext": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("CurrentType", OUT, "CurrentMediaCategory"),
        ("NrTracks", OUT, "NumberOfTracks"),
        ("MediaDuration", OUT, "CurrentMediaDuration"),
        ("CurrentURI", OUT, "AVTransportURI"),
        ("CurrentURIMetaData", OUT, "AVTransportURIMetaData"),
        ("NextURI", OUT, "NextAVTransportURI"),
        ("NextURIMetaData", OUT, "NextAVTransportURIMetaData"),
        ("PlayMedium", OUT, "PlaybackStorageMedium"),
        ("RecordMedium", OUT, "RecordStorageMedium"),
        ("WriteStatus", OUT, "RecordMediumWriteStatus"),
    ],
    "GetTransportInfo": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("CurrentTransportState", OUT, "TransportState"),
        ("CurrentTransportStatus", OUT, "TransportStatus"),
        ("CurrentSpeed", OUT, "TransportPlaySpeed"),
    ],
    "GetPositionInfo": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Track", OUT, "CurrentTrack"),
        ("TrackDuration", OUT, "CurrentTrackDuration"),
        ("TrackMetaData", OUT, "CurrentTrackMetaData"),
        ("TrackURI", OUT, "CurrentTrackURI"),
        ("RelTime", OUT, "RelativeTimePosition"),
        ("AbsTime", OUT, "AbsoluteTimePosition"),
        ("RelCount", OUT, "RelativeCounterPosition"),
        ("AbsCount", OUT, "AbsoluteCounterPosition"),
    ],
    "GetDeviceCapabilities": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("PlayMedia", OUT, "PossiblePlaybackStorageMedia"),
        ("RecMedia", OUT, "PossibleRecordStorageMedia"),
        ("RecQualityModes", OUT, "PossibleRecordQualityModes"),
    ],
    "GetTransportSettings": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("PlayMode", OUT, "CurrentPlayMode"),
        ("RecQualityMode", OUT, "CurrentRecordQualityMode"),
    ],
    "Stop": [("InstanceID", IN, "A_ARG_TYPE_InstanceID")],
    "Play": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Speed", IN, "TransportPlaySpeed"),
    ],
    "Pause": [("InstanceID", IN, "A_ARG_TYPE_InstanceID")],
    "Seek": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Unit", IN, "A_ARG_TYPE_SeekMode"),
        ("Target", IN, "A_ARG_TYPE_SeekTarget"),
    ],
    "Next": [("InstanceID", IN, "A_ARG_TYPE_InstanceID")],
    "Previous": [("InstanceID", IN, "A_ARG_TYPE_InstanceID")],
    "SetPlayMode": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("NewPlayMode", IN, "CurrentPlayMode"),
    ],
    "GetCurrentTransportActions": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Actions", OUT, "CurrentTransportActions"),
    ],
    "X_DLNA_GetBytePositionInfo": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("TrackSize", OUT, "X_DLNA_A_ARG_TYPE_TrackSize"),
        ("RelByte", OUT, "X_DLNA_A_ARG_TYPE_RelByte"),
        ("AbsByte", OUT, "X_DLNA_A_ARG_TYPE_AbsByte"),
    ],
}

AVT_VARS = [
    ("TransportState", "string", True,
     ["STOPPED", "PLAYING", "PAUSED_PLAYBACK", "TRANSITIONING", "NO_MEDIA_PRESENT"], None),
    ("TransportStatus", "string", True, ["OK", "ERROR_OCCURRED"], None),
    ("PlaybackStorageMedium", "string", True, ["NONE", "NETWORK", "HDD", "UNKNOWN"], None),
    ("RecordStorageMedium", "string", True, ["NOT_IMPLEMENTED"], None),
    ("PossiblePlaybackStorageMedia", "string", True, None, None),
    ("PossibleRecordStorageMedia", "string", True, None, None),
    ("CurrentPlayMode", "string", True,
     ["NORMAL", "REPEAT_ONE", "REPEAT_ALL", "SHUFFLE"], None),
    ("TransportPlaySpeed", "string", True, ["1"], None),
    ("RecordMediumWriteStatus", "string", True, ["NOT_IMPLEMENTED"], None),
    ("CurrentRecordQualityMode", "string", True, ["NOT_IMPLEMENTED"], None),
    ("PossibleRecordQualityModes", "string", True, None, None),
    ("NumberOfTracks", "ui4", True, None, (0, 65535, 1)),
    ("CurrentTrack", "ui4", True, None, (0, 65535, 1)),
    ("CurrentTrackDuration", "string", True, None, None),
    ("CurrentMediaDuration", "string", True, None, None),
    ("CurrentTrackMetaData", "string", True, None, None),
    ("CurrentTrackURI", "string", True, None, None),
    ("AVTransportURI", "string", True, None, None),
    ("AVTransportURIMetaData", "string", True, None, None),
    ("NextAVTransportURI", "string", True, None, None),
    ("NextAVTransportURIMetaData", "string", True, None, None),
    ("CurrentTransportActions", "string", True, None, None),
    ("CurrentMediaCategory", "string", True, ["NO_MEDIA", "TRACK_AWARE", "TRACK_UNAWARE"], None),
    ("RelativeTimePosition", "string", False, None, None),
    ("AbsoluteTimePosition", "string", False, None, None),
    ("RelativeCounterPosition", "i4", False, None, None),
    ("AbsoluteCounterPosition", "i4", False, None, None),
    ("LastChange", "string", True, None, None),
    ("A_ARG_TYPE_SeekMode", "string", False,
     ["TRACK_NR", "REL_TIME", "ABS_TIME", "ABS_COUNT", "REL_COUNT"], None),
    ("A_ARG_TYPE_SeekTarget", "string", False, None, None),
    ("A_ARG_TYPE_InstanceID", "ui4", False, None, None),
    ("X_DLNA_A_ARG_TYPE_TrackSize", "string", False, None, None),
    ("X_DLNA_A_ARG_TYPE_RelByte", "string", False, None, None),
    ("X_DLNA_A_ARG_TYPE_AbsByte", "string", False, None, None),
]

# ── RenderingControl ───────────────────────────────────────────────────────
RCS_ACTIONS = {
    "ListPresets": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("CurrentPresetNameList", OUT, "PresetNameList"),
    ],
    "SelectPreset": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("PresetName", IN, "A_ARG_TYPE_PresetName"),
    ],
    "GetVolume": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Channel", IN, "A_ARG_TYPE_Channel"),
        ("CurrentVolume", OUT, "Volume"),
    ],
    "SetVolume": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Channel", IN, "A_ARG_TYPE_Channel"),
        ("DesiredVolume", IN, "Volume"),
    ],
    "GetVolumeDB": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Channel", IN, "A_ARG_TYPE_Channel"),
        ("CurrentVolume", OUT, "VolumeDB"),
    ],
    "SetVolumeDB": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Channel", IN, "A_ARG_TYPE_Channel"),
        ("DesiredVolume", IN, "VolumeDB"),
    ],
    "GetVolumeDBRange": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Channel", IN, "A_ARG_TYPE_Channel"),
        ("MinValue", OUT, "VolumeDB"),
        ("MaxValue", OUT, "VolumeDB"),
    ],
    "GetMute": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Channel", IN, "A_ARG_TYPE_Channel"),
        ("CurrentMute", OUT, "Mute"),
    ],
    "SetMute": [
        ("InstanceID", IN, "A_ARG_TYPE_InstanceID"),
        ("Channel", IN, "A_ARG_TYPE_Channel"),
        ("DesiredMute", IN, "Mute"),
    ],
}

RCS_VARS = [
    ("PresetNameList", "string", False, None, None),
    ("LastChange", "string", True, None, None),
    ("Mute", "boolean", False, None, None),
    ("Volume", "ui2", False, None, (0, 100, 1)),
    ("VolumeDB", "i2", False, None, None),
    ("A_ARG_TYPE_Channel", "string", False, ["Master"], None),
    ("A_ARG_TYPE_InstanceID", "ui4", False, None, None),
    ("A_ARG_TYPE_PresetName", "string", False, ["FactoryDefaults"], None),
]

# ── ConnectionManager ──────────────────────────────────────────────────────
CMS_ACTIONS = {
    "GetProtocolInfo": [
        ("Source", OUT, "SourceProtocolInfo"),
        ("Sink", OUT, "SinkProtocolInfo"),
    ],
    "GetCurrentConnectionIDs": [
        ("ConnectionIDs", OUT, "CurrentConnectionIDs"),
    ],
    "GetCurrentConnectionInfo": [
        ("ConnectionID", IN, "A_ARG_TYPE_ConnectionID"),
        ("RcsID", OUT, "A_ARG_TYPE_RcsID"),
        ("AVTransportID", OUT, "A_ARG_TYPE_AVTransportID"),
        ("ProtocolInfo", OUT, "A_ARG_TYPE_ProtocolInfo"),
        ("PeerConnectionManager", OUT, "A_ARG_TYPE_ConnectionManager"),
        ("PeerConnectionID", OUT, "A_ARG_TYPE_ConnectionID"),
        ("Direction", OUT, "A_ARG_TYPE_Direction"),
        ("Status", OUT, "A_ARG_TYPE_ConnectionStatus"),
    ],
}

CMS_VARS = [
    ("SourceProtocolInfo", "string", True, None, None),
    ("SinkProtocolInfo", "string", True, None, None),
    ("CurrentConnectionIDs", "string", True, None, None),
    ("A_ARG_TYPE_ConnectionStatus", "string", False,
     ["OK", "ContentFormatMismatch", "InsufficientBandwidth",
      "UnreliableChannel", "Unknown"], None),
    ("A_ARG_TYPE_ConnectionManager", "string", False, None, None),
    ("A_ARG_TYPE_Direction", "string", False, ["Input", "Output"], None),
    ("A_ARG_TYPE_ProtocolInfo", "string", False, None, None),
    ("A_ARG_TYPE_ConnectionID", "i4", False, None, None),
    ("A_ARG_TYPE_AVTransportID", "i4", False, None, None),
    ("A_ARG_TYPE_RcsID", "i4", False, None, None),
]


def build_scpd(actions, variables):
    out = ['<?xml version="1.0" encoding="utf-8"?>',
           '<scpd xmlns="urn:schemas-upnp-org:service-1-0">',
           '<specVersion><major>1</major><minor>0</minor></specVersion>',
           '<actionList>']
    for name, args in actions.items():
        out.append(f'<action><name>{name}</name><argumentList>')
        for arg, direction, statevar in args:
            out.append(
                f'<argument><name>{arg}</name><direction>{direction}</direction>'
                f'<relatedStateVariable>{statevar}</relatedStateVariable></argument>')
        out.append('</argumentList></action>')
    out.append('</actionList><serviceStateTable>')
    for name, dtype, events, allowed, rng in variables:
        out.append(f'<stateVariable sendEvents="{"yes" if events else "no"}">'
                   f'<name>{name}</name><dataType>{dtype}</dataType>')
        if allowed:
            out.append('<allowedValueList>' +
                       "".join(f'<allowedValue>{v}</allowedValue>' for v in allowed) +
                       '</allowedValueList>')
        if rng:
            out.append(f'<allowedValueRange><minimum>{rng[0]}</minimum>'
                       f'<maximum>{rng[1]}</maximum><step>{rng[2]}</step>'
                       '</allowedValueRange>')
        out.append('</stateVariable>')
    out.append('</serviceStateTable></scpd>')
    return "".join(out)


AVT_SCPD = build_scpd(AVT_ACTIONS, AVT_VARS)
RCS_SCPD = build_scpd(RCS_ACTIONS, RCS_VARS)
CMS_SCPD = build_scpd(CMS_ACTIONS, CMS_VARS)

# Formatos que mpv reproduce. La lista es amplia a propósito: un Sink
# ProtocolInfo corto hace que algunos controladores rechacen el contenido
# antes siquiera de intentar el SetAVTransportURI.
_MIMES = [
    # Los formatos de subtítulo van primero: hay controladores que solo
    # inspeccionan el principio del Sink para decidir si hay soporte.
    "smi/caption", "text/srt", "text/vtt", "text/sami", "text/ssa",
    "application/x-subrip", "application/smil", "application/ttml+xml",
    "video/mp4", "video/x-matroska", "video/webm", "video/mpeg", "video/avi",
    "video/x-msvideo", "video/quicktime", "video/x-flv", "video/3gpp",
    "video/x-ms-wmv", "video/x-ms-asf", "video/mp2t", "video/MP2T",
    "video/vnd.dlna.mpeg-tts", "video/x-m4v", "video/ogg", "video/divx",
    "application/x-mpegURL", "application/vnd.apple.mpegurl",
    "application/dash+xml", "application/octet-stream",
    "audio/mpeg", "audio/mp4", "audio/aac", "audio/x-aac", "audio/flac",
    "audio/x-flac", "audio/ogg", "audio/vorbis", "audio/opus", "audio/wav",
    "audio/x-wav", "audio/L16", "audio/x-ms-wma", "audio/mpegurl",
    "image/jpeg", "image/png", "image/gif", "image/bmp", "image/webp",
    "text/srt", "text/vtt", "text/plain", "application/x-subrip",
    "smi/caption", "application/ttml+xml",
]

SINK_PROTOCOL_INFO = ",".join(
    f"http-get:*:{mime}:*" for mime in _MIMES
) + ",rtsp-rtp-udp:*:*:*"


def device_xml(cfg):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0" xmlns:dlna="urn:schemas-dlna-org:device-1-0" xmlns:sec="http://www.sec.co.kr/dlna" xmlns:pnpx="http://schemas.microsoft.com/windows/pnpx/2005/11" xmlns:df="http://schemas.microsoft.com/windows/2008/09/devicefoundation">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <dlna:X_DLNADOC xmlns:dlna="urn:schemas-dlna-org:device-1-0">DMR-1.50</dlna:X_DLNADOC>
    <pnpx:X_compatibleId>MS_DigitalMediaDeviceClass_DMR_V001</pnpx:X_compatibleId>
    <pnpx:X_deviceCategory>MediaDevices</pnpx:X_deviceCategory>
    <df:X_deviceCategory>Multimedia.DMR</df:X_deviceCategory>
    <friendlyName>{cfg.name}</friendlyName>
    <manufacturer>cast-dlna</manufacturer>
    <manufacturerURL>https://mpv.io</manufacturerURL>
    <modelDescription>Renderer DLNA/UPnP con mpv</modelDescription>
    <modelName>cast-dlna</modelName>
    <modelNumber>1.0</modelNumber>
    <modelURL>https://mpv.io</modelURL>
    <serialNumber>{cfg.udn[-12:]}</serialNumber>
    <UDN>{cfg.udn}</UDN>
    <iconList>
      <icon><mimetype>image/png</mimetype><width>48</width><height>48</height>
        <depth>24</depth><url>/icon.png</url></icon>
    </iconList>
    <serviceList>
      <service>
        <serviceType>{AVT}</serviceType>
        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
        <SCPDURL>/scpd/avt.xml</SCPDURL>
        <controlURL>/ctrl/avt</controlURL>
        <eventSubURL>/evt/avt</eventSubURL>
      </service>
      <service>
        <serviceType>{RCS}</serviceType>
        <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
        <SCPDURL>/scpd/rcs.xml</SCPDURL>
        <controlURL>/ctrl/rcs</controlURL>
        <eventSubURL>/evt/rcs</eventSubURL>
      </service>
      <service>
        <serviceType>{CMS}</serviceType>
        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
        <SCPDURL>/scpd/cms.xml</SCPDURL>
        <controlURL>/ctrl/cms</controlURL>
        <eventSubURL>/evt/cms</eventSubURL>
      </service>
    </serviceList>
    <!-- Marcador de capacidades de Samsung. Los controladores que mandan los
         subtítulos por la vía `sec:CaptionInfoEx` (Web Video Caster entre
         ellos) lo usan para decidir si el renderer los soporta; sin él
         declaran el dispositivo como «sin soporte para subtítulos» aunque el
         Sink anuncie text/srt. `Captions` es la capacidad relevante. -->
    <sec:ProductCap>Y2020,WebURIPlayable,SeekTRACK_NR,NavigateInPause,Captions</sec:ProductCap>
    <sec:X_ProductCap>Y2020,WebURIPlayable,SeekTRACK_NR,NavigateInPause,Captions</sec:X_ProductCap>
    <pnpx:X_hardwareId>VEN_0105&amp;DEV_VD0001</pnpx:X_hardwareId>
    <presentationURL>{cfg.base_url}/</presentationURL>
  </device>
</root>"""
