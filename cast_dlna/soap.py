"""Serialización y parseo SOAP para las peticiones de control UPnP."""

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

ERRORS = {
    401: "Invalid Action",
    402: "Invalid Args",
    501: "Action Failed",
    600: "Argument Value Invalid",
    601: "Argument Value Out of Range",
    602: "Optional Action Not Implemented",
    701: "Transition not available",
    712: "Play mode not supported",
    710: "Seek mode not supported",
    711: "Illegal seek target",
    714: "Illegal MIME-type",
    716: "Resource not found",
}


def parse_action(soap_action_header, body):
    """Devuelve (nombre_accion, {arg: valor}) a partir de la petición."""
    action = ""
    m = re.search(r'[#"]([\w:.\-]+)"?\s*$', soap_action_header or "")
    if m:
        action = m.group(1).split("#")[-1].strip('"')

    args = {}
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return action, _args_with_regex(body)

    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        if tag in ("Envelope", "Body", "Header"):
            continue
        if not action:
            action = tag
            continue
        if tag == action:
            continue
        args[tag] = elem.text or ""
    return action, args


def _args_with_regex(body):
    args = {}
    for tag, value in re.findall(r"<(?:\w+:)?(\w+)[^>]*>(.*?)</(?:\w+:)?\1>",
                                 body or "", re.S):
        if tag not in ("Envelope", "Body", "Header"):
            args.setdefault(tag, value)
    return args


def response(action, service_type, values=None):
    parts = "".join(
        f"<{name}>{escape(str(value))}</{name}>"
        for name, value in (values or {}).items())
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action}Response xmlns:u="{service_type}">'
        f'{parts}'
        f'</u:{action}Response></s:Body></s:Envelope>'
    )


def fault(code, description=""):
    description = description or ERRORS.get(code, "Action Failed")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><s:Fault>'
        '<faultcode>s:Client</faultcode><faultstring>UPnPError</faultstring>'
        '<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0">'
        f'<errorCode>{code}</errorCode>'
        f'<errorDescription>{escape(description)}</errorDescription>'
        '</UPnPError></detail>'
        '</s:Fault></s:Body></s:Envelope>'
    )


def unescape(text):
    if not text:
        return ""
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                         ("&apos;", "'"), ("&#39;", "'"), ("&#34;", '"'),
                         ("&amp;", "&")):
        text = text.replace(entity, char)
    return text
