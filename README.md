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

### Imágenes

Un cast de una foto tiene que quedarse en pantalla hasta que el controlador
mande otra cosa, pero mpv descarta las imágenes a los `image-display-duration`
segundos —5 por defecto— y con `keep-open=no` vuelve a idle: la foto aparecía
unos instantes y desaparecía.

Al reconocer contenido de imagen —por `upnp:class` con `imageItem`, por MIME
`image/*` o por la extensión de la URI— se pone `image-display-duration=inf`,
y se restaura el valor normal en el siguiente cast. El estado se reporta como
`PLAYING` mientras la imagen está en pantalla: una imagen fija deja a mpv en
`core-idle`, y sin ese caso el controlador se quedaría en «cargando» para
siempre.

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

**Compartir pantalla** (CastLab y similares) llega como un MPEG-TS en vivo
(`video/mp2t`) por HTTP chunked. Al detectar ese MIME se activa el perfil
`low-latency` de mpv y se desactivan cache y readahead; si además el stream no
trae pista de audio, se activa `untimed`. Sin audio mpv no tiene reloj al que
engancharse y el desfase contra los timestamps del emisor se acumula, así que
el retraso crece con el tiempo. Medido con `scripts/measure-live-latency.py`:

| | por defecto | `--no-live-latency` |
|---|---|---|
| `demuxer-cache-duration` | 0,0 s | 1,5 s |
| `untimed` | sí | no |
| `audio-buffer` | 0,0 s | 0,2 s |

`--no-live-latency` restaura el comportamiento de VOD si algún stream sufre
cortes por falta de búfer.

`untimed` se retira en cuanto aparece la pista de audio: en un MPEG-TS no
figura en el `track-list` hasta que llega su primer paquete, casi siempre
después de `file-loaded`, así que decidirlo solo ahí lo dejaba puesto sobre
streams que sí tenían audio.

Repartiendo la latencia de un compartir pantalla medida en esta máquina: el
demuxer del receptor retiene 33 ms y la red aporta ~4 ms de ida y vuelta. Lo
que se perciba por encima de eso viene de la captura y el codificador del
emisor.

## Volumen

Tres controles distintos se confunden con facilidad, y solo uno llega hasta
aquí:

| Control | Ruta | ¿Afecta al receptor? |
|---|---|---|
| Volumen multimedia del teléfono (botones físicos) | índice del dispositivo `speaker` | **No.** La captura de pantalla viaja por `remote_submix`, que tiene índice propio: con el altavoz a 0 sigue en 15/15 |
| Volumen del audio dentro de un compartir pantalla | va incrustado en el MPEG-TS | Solo el nivel al que sonara en el emisor |
| Volumen del cast (slider del controlador) | `RenderingControl::SetVolume` | **Sí** — es el único que mueve mpv |

`--remote-volume` decide qué hacer con el tercero:

| Modo | Comportamiento |
|---|---|
| `auto` *(default)* | Lo aplica salvo en compartir pantalla, donde se ignora |
| `always` | Lo aplica siempre (DLNA estricto) |
| `never` | Nunca lo aplica; el volumen se gestiona solo en este equipo |

Compartir pantalla se reconoce por dos señales a la vez: MIME de directo
(`video/mp2t`) **y** URI servida por la misma IP que manda el SOAP — el emisor
sirviéndose a sí mismo. Por separado no bastan: IPTV en directo también es
`mp2t` pero desde otro host, y Web Video Caster monta un proxy local que sirve
mp4 desde el propio teléfono.

Un `SetVolume` descartado se responde igualmente con `200 OK` —un fault haría
que el controlador diera el renderer por roto— pero `GetVolume` sigue
devolviendo el valor real de mpv, así que el slider del móvil salta de vuelta
en lugar de mentir sobre el estado del reproductor.

## Compatibilidad con controladores (cont.)

**Subtítulos**: además de anunciar los MIME de subtítulo al principio del
`Sink` de `GetProtocolInfo`, el `device.xml` declara `sec:ProductCap` /
`sec:X_ProductCap` (marcador de capacidades de Samsung). Los controladores que
mandan los subtítulos por `sec:CaptionInfoEx` — Web Video Caster entre ellos —
lo usan para decidir si el renderer los soporta.

## Cambios de dirección IP

El UDN es estable entre arranques a propósito: los controladores recuerdan el
dispositivo por él, y uno aleatorio crearía una entrada nueva en la lista del
móvil cada vez. El efecto secundario es que también cachean la `LOCATION`
asociada a ese UDN, con `max-age` de 30 minutos.

Con DHCP la dirección se mueve, y entonces el controlador sigue pidiendo el
`device.xml` a una IP que ya no existe: el renderer «desaparece» o deja de
responder, y vuelve solo cuando caduca la caché o llega el siguiente `NOTIFY`
periódico —hasta 10 minutos—. De ahí que se comporte de forma intermitente.

El renderer vigila su IP de salida cada 10 s. Al detectar un cambio manda
`ssdp:byebye` con la identidad vieja, actualiza la `LOCATION`, incrementa el
`BOOTID` —la señal de UPnP 1.1 para «olvida lo que sabías»— rehace la
suscripción al grupo multicast en la interfaz nueva y emite una ráfaga de
`ssdp:alive`. Verificable con `scripts/test-ip-change.py`.

Las respuestas a `M-SEARCH` salen además por el socket que escucha en el 1900,
para que le lleguen al controlador desde el mismo puerto al que preguntó, y se
envían por duplicado: UDP sobre wifi se pierde.

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

`scripts/live-ts-source.py` — emite un MPEG-TS en vivo solo-vídeo por HTTP
chunked, idéntico en forma al «screen share» de CastLab, para reproducir el
caso sin el móvil.

`scripts/measure-live-latency.py <puerto> <socket-mpv>` — castea ese stream y
reporta el retraso retenido en el demuxer. Comparar con y sin
`--no-live-latency`.

`scripts/test-volume-policy.py` — levanta un receptor por cada modo de
`--remote-volume` y comprueba los tres escenarios (compartir pantalla, directo
ajeno, vídeo normal) contra lo esperado.

`scripts/probe-capture-volume.sh <ip-móvil>` — mide el nivel del audio que
llega en un compartir pantalla a distintos volúmenes del teléfono, para
comprobar en tu dispositivo que la captura no depende de ellos.

## Dependencias

- `mpv` en el `PATH`
- Para compilar: `nuitka` y `gcc`
- Para ejecutar el binario: nada más

## Ejecutar sin compilar

```bash
python3 cast-dlna.py --name Test -v
```
