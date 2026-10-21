<div align="center">

# cast-dlna

**Receptor DLNA/UPnP completo para el escritorio Linux, con mpv como reproductor.**

![Licencia](https://img.shields.io/badge/licencia-GPL--3.0--or--later-FF6B00?style=flat-square&labelColor=1A1A1A)
![Plataforma](https://img.shields.io/badge/plataforma-Linux-3A3A3A?style=flat-square&labelColor=1A1A1A)
![Python](https://img.shields.io/badge/Python-3-3A3A3A?style=flat-square&logo=python&labelColor=1A1A1A)

</div>

---

## Qué es

cast-dlna convierte el ordenador en un destino para «enviar a» desde el teléfono. Se anuncia en
la red local como `MediaRenderer:1` (DMR-1.50) y acepta los comandos que envían los
controladores DLNA habituales —Web Video Caster, BubbleUPnP, VLC, Kodi o «Reproducir en» de
Windows—, incluidos búsqueda, volumen, listas de reproducción y subtítulos. La reproducción
corre en **mpv**, sin relanzarlo en cada envío.

## Funciones principales

- AVTransport, RenderingControl y ConnectionManager completos, con eventos GENA.
- Subtítulos, imágenes y directos.
- Políticas de volumen configurables.
- Se recupera solo de los cambios de dirección IP.
- Binario único de unos 10 MB, sin dependencias de Python en el sistema.

## Tecnologías

| Capa | Tecnología |
|---|---|
| Protocolos | UPnP AV: SSDP, SOAP y GENA, implementados sin librerías externas |
| Reproductor | mpv, controlado por su IPC JSON |
| Lenguaje | Python 3, biblioteca estándar |
| Empaquetado | Nuitka |

## Puesta en marcha

Requiere `mpv` en el `PATH`.

```bash
python3 cast-dlna.py --name "Salón"      # sin compilar
./build.sh --install                     # binario con Nuitka en ~/.local/bin/cast-dlna
cast-dlna --fullscreen -v
```

## Emisor con audio

Para compartir la pantalla del teléfono **con sonido**, el emisor recomendado es
[CastLabNV](https://github.com/noctivulp-ch/CastLabNV), un fork de CastLab que añade el
audio de reproducción al stream.

## Documentación

- [`docs/guia.md`](docs/guia.md): comandos soportados, compatibilidad con cada controlador,
  volumen, cambios de IP y arquitectura.
- [`docs/callejones-recorridos.md`](docs/callejones-recorridos.md): lo que se probó y no funcionó.

## Licencia

Código bajo **GPL-3.0-or-later** ([`LICENSE`](LICENSE)). Los componentes de terceros y sus licencias
están en [`NOTICE`](NOTICE). El nombre y la identidad visual no forman parte de la licencia: ver
[`TRADEMARKS.md`](TRADEMARKS.md). Para aportar, [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Apoyo

Este proyecto forma parte del trabajo de **NoctiVulp**: herramientas para Linux y Android,
publicadas como software libre. Las compilaciones oficiales y las novedades salen en Patreon.

<p align="center">
  <a href="https://www.patreon.com/cw/NoctiVulp"><img src="https://img.shields.io/badge/Patreon-NoctiVulp-FF6B00?style=for-the-badge&logo=patreon&logoColor=white&labelColor=1A1A1A" alt="NoctiVulp en Patreon"></a>
</p>

---

<p align="center"><sub>© 2026 NoctiVulp · <b>Powered by AI</b> — desarrollado con la asistencia de Claude, de Anthropic.</sub></p>
