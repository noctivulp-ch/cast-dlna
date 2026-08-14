# cast-dlna

Renderer DLNA/UPnP completo (`MediaRenderer:1`, DMR-1.50) con **mpv** como
único backend. Se anuncia en la LAN y acepta el conjunto completo de comandos
que envían los controladores DLNA — Web Video Caster, BubbleUPnP, VLC, Kodi,
Windows «Reproducir en» —, incluidos seek, volumen, playlist y subtítulos.

Sucesor de [`dlna-haruna`](../dlna-haruna/), que solo soportaba
`SetAVTransportURI` / `Play` / `Stop` / `Pause` y relanzaba el reproductor en
cada cast.

## Instalación

```bash
./build.sh --install     # compila con Nuitka y enlaza ~/.local/bin/cast-dlna
```

Deja un binario único de ~10 MB en `dist/cast-dlna` (sin dependencias de
Python en el sistema) y el symlink `~/.local/bin/cast-dlna`.

## Uso

```bash
cast-dlna                                   # nombre = hostname, puerto 8201
cast-dlna --name "Salón"                    # nombre visible en el móvil
cast-dlna --port 8210
cast-dlna --fullscreen                      # cada cast abre a pantalla completa
cast-dlna --mpv-args "--hwdec=auto --volume=70"
cast-dlna -v                                # log de cada SOAP/GENA recibido
```

`http://<ip>:<puerto>/status` devuelve el estado en texto plano.

## Comandos soportados

### AVTransport:1

| Acción | Comportamiento |
|---|---|
| `SetAVTransportURI` | Carga URI + metadata DIDL (título, subtítulos, cabeceras) |
| `SetNextAVTransportURI` | Encola el siguiente elemento en la playlist de mpv |
| `Play` / `Pause` / `Stop` | Control real por IPC, sin matar el proceso |
| `Seek` | `REL_TIME`, `ABS_TIME` y `TRACK_NR` |
| `Next` / `Previous` | Navegación de playlist |
| `SetPlayMode` | `NORMAL`, `REPEAT_ONE`, `REPEAT_ALL`, `SHUFFLE` |
| `GetPositionInfo` | Posición y duración reales |
| `GetMediaInfo` / `GetMediaInfo_Ext` | |
| `GetTransportInfo` | `PLAYING` / `PAUSED_PLAYBACK` / `STOPPED` / `TRANSITIONING` / `NO_MEDIA_PRESENT` |
| `GetTransportSettings` / `GetDeviceCapabilities` | |
| `GetCurrentTransportActions` | Acciones válidas según el estado actual |
| `X_DLNA_GetBytePositionInfo` | Extensión DLNA |

### RenderingControl:1

`ListPresets`, `SelectPreset`, `GetVolume`, `SetVolume`, `GetVolumeDB`,
`SetVolumeDB`, `GetVolumeDBRange`, `GetMute`, `SetMute`.

### ConnectionManager:1

`GetProtocolInfo`, `GetCurrentConnectionIDs`, `GetCurrentConnectionInfo`.

### Eventos (GENA)

`SUBSCRIBE`, renovación por `SID`, `UNSUBSCRIBE` y `NOTIFY` con `LastChange`
para AVTransport y RenderingControl. Sin esto, el controlador no refresca la
barra de progreso ni el botón play/pausa: es la diferencia práctica frente al
renderer anterior.

### Subtítulos

Se detectan por las cuatro vías que usan los controladores, en este orden:

1. `<sec:CaptionInfoEx>` / `<sec:CaptionInfo>` (Samsung)
2. `<pv:subtitleFileUri>` (BubbleUPnP, Web Video Caster)
3. `<res protocolInfo="http-get:*:text/srt:*">` u otro `res` con MIME de texto
4. Cabecera `CaptionInfo.sec` en la respuesta HTTP del propio recurso

Se cargan con `sub-add` una vez mpv abre el archivo, y quedan seleccionados.

### Cabeceras HTTP

`Referer`, `User-Agent`, `Cookie` y `Authorization` se propagan a mpv
(`--referrer`, `--user-agent`, `http-header-fields`). Si el controlador no
manda `Referer`, se deriva del dominio del stream: sin él, muchos sitios
devuelven 403 al reproducir desde el escritorio.

## Compatibilidad con controladores

**CastLab** comprueba que el dispositivo sigue vivo con `HEAD /device.xml` en
cada ciclo de polling, y valida el icono con `HEAD /icon.png`. Una respuesta a
`HEAD` debe llevar `Content-Length` pero **nunca cuerpo**: con keep-alive de
HTTP/1.1 el cliente lee ese cuerpo como la línea de estado de la respuesta
siguiente (`BadStatusLine`) y da el dispositivo por inalcanzable — CastLab
llama entonces a `disconnect()` y responde «ningún dispositivo conectado» al
pulsar reproducir, aunque el descubrimiento y la conexión hubiesen ido bien.

**Subtítulos**: además de anunciar los MIME de subtítulo al principio del
`Sink` de `GetProtocolInfo`, el `device.xml` declara `sec:ProductCap` /
`sec:X_ProductCap` (marcador de capacidades de Samsung). Los controladores que
mandan los subtítulos por `sec:CaptionInfoEx` — Web Video Caster entre ellos —
lo usan para decidir si el renderer los soporta.

## Arquitectura

```
Controlador DLNA (Web Video Caster, BubbleUPnP…)
  │
  ├─ SSDP UDP 239.255.255.250:1900 ─→ ssdp.py       descubrimiento + anuncio
  │
  └─ HTTP TCP :8201 ────────────────→ server.py     rutas UPnP
        ├─ GET  /device.xml, /scpd/*.xml            device.py (SCPD generados)
        ├─ POST /ctrl/{avt,rcs,cms}                 soap.py → renderer.py
        └─ SUBSCRIBE /evt/{avt,rcs,cms}             gena.py → NOTIFY LastChange
                                                        │
                                              renderer.py (estado UPnP)
                                                        │
                                              player.py ─ IPC JSON ─→ mpv
```

`mpv` se lanza **una sola vez** en `--idle=yes --force-window=no` y persiste
entre casts: la ventana aparece al reproducir y desaparece al parar, pero el
socket IPC nunca se pierde. Eso es lo que hace posible implementar seek,
volumen, posición y eventos de verdad.

| Módulo | Responsabilidad |
|---|---|
| `config.py` | Argumentos, IP de salida, UDN estable derivado de la MAC |
| `player.py` | Proceso mpv persistente, IPC JSON, propiedades observadas |
| `didl.py` | Parseo DIDL-Lite: título, duración, subtítulos, cabeceras |
| `soap.py` | Parseo de peticiones y respuestas/faults SOAP |
| `device.py` | `device.xml` y los tres SCPD, generados desde tablas |
| `gena.py` | Suscripciones y `NOTIFY` con `LastChange` |
| `renderer.py` | Implementación de las acciones sobre el player |
| `server.py` | HTTP (`GET`, `POST`, `SUBSCRIBE`, `UNSUBSCRIBE`) |
| `ssdp.py` | M-SEARCH y anuncios `ssdp:alive` / `ssdp:byebye` |

## scripts/

`scripts/probe-renderer.py` — controlador DLNA mínimo para probar sin móvil:

```bash
./scripts/probe-renderer.py                                  # descubrir renderers
./scripts/probe-renderer.py --url http://IP:8201/device.xml --suite
./scripts/probe-renderer.py --url ... --cast URL --sub URL.srt
./scripts/probe-renderer.py --url ... --events               # escuchar GENA
```

`--suite` ejecuta las 27 acciones y reporta OK/fallo por cada una. Sirve
igual para auditar renderers de terceros.

## Dependencias

- `mpv` en el `PATH`
- Para compilar: `nuitka` y `gcc`
- Para ejecutar el binario: nada más

## Ejecutar sin compilar

```bash
python3 cast-dlna.py --name Test -v
```
