# Pendientes y callejones ya recorridos

## Retraso del compartir pantalla — cerrado sin resolver

El compartir pantalla llega con un retraso que crece con el tiempo, del orden
de un segundo o dos tras un rato de emisión. Se dio por aceptable: lo que se
usa a diario —vídeo, imágenes y música desde CastLab, y vídeo web desde Web
Video Caster— va bien.

Queda escrito lo que **no** funciona, para no volver a intentarlo:

| Vía | Por qué no |
|---|---|
| Ajustar la velocidad de reproducción | Cualquier valor distinto de 1,0, hacia arriba o hacia abajo, satura el audio en este receptor. El perfil de baja latencia deja `audio-buffer=0` y el filtro de tempo no tiene margen |
| `seek` para saltar a lo último recibido | Un directo por HTTP no es *seekable*; mpv lo ignora en silencio y el atraso no se mueve |
| Regular sobre `demuxer-cache-duration` | No mide retraso, sino datos por delante sin reproducir. Con un emisor que entrega a ráfagas sube y baja sin relación con la latencia: ante una ráfaga la corrección acelera, consume el colchón y deja seco al reproductor |
| Promediar esa señal antes de corregir | La media retrasa la reacción tanto como su constante de tiempo: con el búfer ya vacío seguía marcando lleno y acelerando |

Lo que sí está medido y funciona, por si se retoma:

- `scripts/measure-total-latency.sh` — latencia de punta a punta, del toque en
  la pantalla del teléfono al cambio en los altavoces. Repetida en el tiempo
  distingue un retardo fijo de una deriva.
- `scripts/measure-glass-to-glass.sh` — captura, codificación y red por
  separado: 53–113 ms medidos.
- `scripts/measure-audio-rate.sh` — si el emisor entrega audio al ritmo del
  reloj (99,6 % tras arreglar su bucle de cadencia).

Para retomarlo haría falta **una señal que mida el retraso de verdad** y **un
actuador que no se oiga**. Lo más prometedor, por orden:

1. Que el emisor selle cada paquete con su reloj y el receptor compare contra
   el suyo tras sincronizarlos. Requiere tocar el parche de CastLab.
2. Recargar el stream cuando el retraso pase de un umbral. Reconectar sí
   descarta el atraso, pero corta la imagen medio segundo; habría que ver si
   molesta menos que el retraso.

## Recibir audio de AudioRelay — idea, sin empezar

Cubrir el caso «poner música de Spotify en los altavoces del PC» sin pasar por
el compartir pantalla, que para eso es un rodeo caro: codifica la pantalla
entera para transportar solo sonido.

AudioRelay ya está instalado en el teléfono y su APK está desmontado en
`lib/audiorelay/` (ver el historial: usa `AudioPlaybackCapture` con los mismos
`addMatchingUsage` que el parche de CastLab). Falta averiguar qué protocolo
usa entre teléfono y PC, y si el receptor puede hablarlo o si sale más a
cuenta que el teléfono emita un stream que este renderer ya sepa reproducir.

Ventaja frente al compartir pantalla: sin vídeo no hay que codificar nada
pesado, y el problema de sincronía A/V desaparece por completo.

## Receptor nativo para Android TV — planificado

Reescritura del receptor como app de Android TV, con
[Wulfenite UI](../../%23Libs/wulfenite_ui) para la interfaz.

El retraso en directo no debería reaparecer allí: ExoPlayer/Media3 trae el
control de velocidad para directos de fábrica (`targetOffsetMs`,
`minPlaybackSpeed`, `maxPlaybackSpeed`), y al no depender de mpv tampoco
arrastra la limitación del `audio-buffer=0`.

Lo que se reutiliza tal cual de este proyecto:

- `scripts/probe-renderer.py` — 27 acciones UPnP contra el receptor nuevo.
- Las decisiones del `device.xml`: `sec:ProductCap` para que los controladores
  acepten subtítulos, y un Sink amplio con los MIME de subtítulo delante.
- Las cuatro vías de detección de subtítulos y la política de volumen.
