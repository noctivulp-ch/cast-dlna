"""SSDP: descubrimiento (M-SEARCH) y anuncio periódico (NOTIFY)."""

import random
import socket
import struct
import threading
import time

from .config import MAX_AGE, SSDP_ADDR, SSDP_PORT

BOOT_ID = int(time.time()) & 0x7FFFFFFF


class SSDP:
    def __init__(self, cfg):
        self.cfg = cfg
        self.running = True
        self.types = [
            "upnp:rootdevice",
            cfg.udn,
            "urn:schemas-upnp-org:device:MediaRenderer:1",
            "urn:schemas-upnp-org:service:AVTransport:1",
            "urn:schemas-upnp-org:service:RenderingControl:1",
            "urn:schemas-upnp-org:service:ConnectionManager:1",
        ]

    def usn(self, target):
        return self.cfg.udn if target == self.cfg.udn else f"{self.cfg.udn}::{target}"

    def start(self):
        threading.Thread(target=self._listener, daemon=True).start()
        threading.Thread(target=self._announcer, daemon=True).start()

    def stop(self):
        self.running = False
        self._notify(alive=False)

    # ── Respuesta a M-SEARCH ───────────────────────────────────────────────
    def _search_response(self, target):
        return (
            "HTTP/1.1 200 OK\r\n"
            f"CACHE-CONTROL: max-age={MAX_AGE}\r\n"
            f"DATE: {time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())}\r\n"
            "EXT:\r\n"
            f"LOCATION: {self.cfg.base_url}/device.xml\r\n"
            "SERVER: Linux/1.0 UPnP/1.0 cast-dlna/1.0\r\n"
            f"ST: {target}\r\n"
            f"USN: {self.usn(target)}\r\n"
            f"BOOTID.UPNP.ORG: {BOOT_ID}\r\n"
            "CONFIGID.UPNP.ORG: 1\r\n"
            "\r\n"
        )

    def _reply(self, addr, targets, delay):
        time.sleep(delay)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for target in targets:
                try:
                    s.sendto(self._search_response(target).encode(), addr)
                except OSError:
                    pass

    def _listener(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        s.bind(("", SSDP_PORT))
        mreq = struct.pack("4s4s", socket.inet_aton(SSDP_ADDR),
                           socket.inet_aton(self.cfg.ip))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        s.settimeout(1.0)

        while self.running:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            msg = data.decode("utf-8", errors="replace")
            if not msg.upper().startswith("M-SEARCH"):
                continue
            headers = _parse_headers(msg)
            if headers.get("man", "").strip('"') != "ssdp:discover":
                continue
            st = headers.get("st", "").strip()
            targets = self._matching(st)
            if not targets:
                continue
            try:
                mx = min(int(headers.get("mx", 1)), 5)
            except ValueError:
                mx = 1
            delay = random.uniform(0, max(0.1, mx * 0.5))
            self.cfg.debug(f"[ssdp] M-SEARCH {st} desde {addr[0]}")
            threading.Thread(target=self._reply, args=(addr, targets, delay),
                             daemon=True).start()
        s.close()

    def _matching(self, st):
        if st == "ssdp:all":
            return list(self.types)
        if st in self.types:
            return [st]
        return []

    # ── Anuncio ────────────────────────────────────────────────────────────
    def _notify(self, alive=True):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                         socket.inet_aton(self.cfg.ip))
        except OSError:
            return
        with s:
            for target in self.types:
                if alive:
                    msg = (
                        "NOTIFY * HTTP/1.1\r\n"
                        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
                        f"CACHE-CONTROL: max-age={MAX_AGE}\r\n"
                        f"LOCATION: {self.cfg.base_url}/device.xml\r\n"
                        f"NT: {target}\r\n"
                        "NTS: ssdp:alive\r\n"
                        "SERVER: Linux/1.0 UPnP/1.0 cast-dlna/1.0\r\n"
                        f"USN: {self.usn(target)}\r\n"
                        f"BOOTID.UPNP.ORG: {BOOT_ID}\r\n"
                        "CONFIGID.UPNP.ORG: 1\r\n"
                        "\r\n"
                    )
                else:
                    msg = (
                        "NOTIFY * HTTP/1.1\r\n"
                        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
                        f"NT: {target}\r\n"
                        "NTS: ssdp:byebye\r\n"
                        f"USN: {self.usn(target)}\r\n"
                        f"BOOTID.UPNP.ORG: {BOOT_ID}\r\n"
                        "CONFIGID.UPNP.ORG: 1\r\n"
                        "\r\n"
                    )
                try:
                    s.sendto(msg.encode(), (SSDP_ADDR, SSDP_PORT))
                except OSError:
                    pass

    def _announcer(self):
        # Ráfaga inicial: el primer anuncio se pierde a menudo si el
        # controlador aún no está escuchando el grupo multicast.
        for _ in range(3):
            self._notify(alive=True)
            time.sleep(0.4)
        while self.running:
            for _ in range(MAX_AGE // 3):
                if not self.running:
                    return
                time.sleep(1)
            self._notify(alive=True)


def _parse_headers(msg):
    headers = {}
    for line in msg.split("\r\n")[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return headers
