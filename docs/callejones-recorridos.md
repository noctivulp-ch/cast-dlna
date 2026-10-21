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

## Anunciarse como Chromecast o pantalla inalámbrica — estudiado, descartado

Se miró la viabilidad de que el receptor se anuncie además como Chromecast o
como pantalla inalámbrica genérica. Ninguna de las dos sale a cuenta.

**Google Cast.** Existe [shanocast](https://github.com/rgerganov/shanocast),
receptor en código abierto sobre Openscreen. El muro es la autenticación: el
emisor verifica al receptor y se niega a emitir si falla, y pasarla exige un
`client_auth_certificate` firmado por Google. Shanocast lo sortea con firmas
precomputadas extraídas de un producto comercial, que además caducan cada dos
días. Y aun así cubre el espejado de Chrome, no las apps de móvil, que usan
identificadores de aplicación registrados. Base inservible para algo propio.

**Miracast.** Existe [MiracleCast](https://github.com/albfan/miraclecast)
(LGPL), con *source* y *sink*. Pero necesita Wi-Fi P2P vía `wpa_supplicant`,
su desarrollo lleva años parado esperando APIs de P2P en los gestores de red,
y sobre todo Android retiró Miracast de AOSP —abandonado en Android 6,
descontinuado desde Android 9—, así que solo sobrevive en capas de fabricante.
Mucho trabajo en el receptor para depender de algo que el emisor está
retirando.

**FCast, en cambio, sí.** Es abierto, sin autenticación de por medio, y CastLab
ya lo habla: `FCastClient.ts`, puerto 46899, descubrimiento por mDNS
`_fcast._tcp`, y un protocolo binario simple de longitud + opcode + JSON. Los
`{"version":3}` que aparecían en el registro del renderer eran CastLab
preguntando si éramos un receptor FCast. Es la ampliación más barata si algún
día se quiere cubrir más emisores.

## Receptor nativo para Android TV — planificado

Reescritura del receptor como app de Android TV, con
[Wulfenite UI](../../%23Libs/wulfenite_ui) para la interfaz.

El retraso en directo no debería reaparecer allí: ExoPlayer/Media3 trae el
control de velocidad para directos de fábrica (`targetOffsetMs`,
`minPlaybackSpeed`, `maxPlaybackSpeed`), y al no depender de mpv tampoco
arrastra la limitación del `audio-buffer=0`.

### Wulfenite UI: revisado, sirve

El paquete `Compose` cubre ya lo que faltaba en la revisión anterior: `Aviso`,
`Controles` (botón primario, botón, botón plano, campo, interruptor) y sobre
todo `foco/Foco.kt`, que era el bloqueante para televisión. 40 pruebas, todas
en verde.

El foco está resuelto con criterio de sala, no de escritorio: canto de 3 dp
*«porque un televisor se mira a tres metros y un escalón de 1 dp ahí no
existe»*, más el pozo aclarado para que se distinga de seleccionado cuando los
dos caen juntos —que es lo normal recorriendo una lista con el mando—. Y los
controles comparten una única `MutableInteractionSource` entre el `clickable`
y el pintado, que es justo el fallo por el que el canto no se entera de nada.

Lo que habría que añadir al montar el receptor:

- **Una barra de progreso enfocable.** No existe ninguna, y en un reproductor
  es la pieza central: sin ella no hay forma de buscar con el mando. Es
  específica de reproductor, así que tiene sentido que no estuviera antes.
- **Foco inicial por pantalla** (`FocusRequester`). No hay ayuda en la
  librería, pero es un par de líneas en cada pantalla de la app.
- El ejemplo es una app de móvil: no declara `LEANBACK_LAUNCHER`, banner ni
  `uses-feature` de televisión. Eso va en el manifest del receptor, no en la
  librería.

Lo que se reutiliza tal cual de este proyecto:

- `scripts/probe-renderer.py` — 27 acciones UPnP contra el receptor nuevo.
- Las decisiones del `device.xml`: `sec:ProductCap` para que los controladores
  acepten subtítulos, y un Sink amplio con los MIME de subtítulo delante.
- Las cuatro vías de detección de subtítulos y la política de volumen.
