# Hello Assistant (macOS High Sierra)

Versión de Hello Assistant para Macs Intel con **macOS High Sierra 10.13.6**.
Mientras está abierta, la compu no se duerme (la pantalla sí puede apagarse).

Diferencias con la versión normal:
- **"Hola asistente" se detecta en la Mac con Vosk** (gratis y sin internet). Solo cuando Vosk
  cree escucharla, ese fragmento se confirma con la API de OpenAI, que también transcribe el
  pedido (en vez de Whisper local).
- **Voz de las respuestas con OpenAI TTS** (en vez de Piper).
- Detector de voz WebRTC VAD (en vez de Silero).
- **mpv 0.33.1** (el último build que funciona en macOS 10.12+).
- **Python 3.12.10 de python.org** (el último instalador de 3.12 y funciona en 10.13).

Motivo: onnxruntime (que usan Piper y Silero) no existe para macOS 10.13, y las versiones
nuevas de mpv y Whisper piden macOS 11 o más. Esta versión no compila nada: todo se instala precompilado.

Necesita internet para responder: el pedido, la respuesta y la voz pasan por OpenAI.
Escuchar la frase de activación, la música, los temporizadores y el índice son locales.

## Instalación y uso
1. Copiá la carpeta `high-sierra` a la Mac con High Sierra (por ejemplo, al Escritorio).
2. Abrí Terminal y ejecutá:
```bash
cd ~/Desktop/high-sierra
./iniciar.sh
```
La primera vez baja mpv a `bin/`, el modelo de Vosk en español (~40 MB) a `models/` y el instalador de Python 3.12 de python.org (se abre solo:
seguí los pasos, te pide la contraseña de la Mac, y volvé a correr `./iniciar.sh`).
Después crea un entorno propio en `.venv/` e instala las dependencias.
Si no existe `.env`, lo crea a partir de `.env.example` para que lo completes.
Si la música está en otra Mac de la red, compartí esas carpetas (Compartir archivos, con acceso de invitado)
y poné su nombre en `SERVIDOR_MUSICA`: `iniciar.sh` las conecta solo antes de abrir la app.

macOS va a pedir permiso de micrófono para la Terminal: aceptalo.
Si mpv no abre ("desarrollador no identificado"), hacé clic derecho sobre `bin/mpv.app`, elegí **Abrir** y luego confirmá.

## Uso por voz
Decí **"Hola asistente"**, esperá el bip y hacé tu pedido.
También podés decirlo de corrido: "Hola asistente, poné el disco de Pink Floyd".

Otros modos:
- `./iniciar.sh --texto`: por texto, sin micrófono.
- `./iniciar.sh --prueba-activacion`: solo cuenta activaciones (OpenAI se usa solo para confirmar posibles frases).
- `./iniciar.sh --debug`: muestra todo lo que transcribe.
- `./iniciar.sh --probar-microfono`: graba 5 segundos, te los repite y muestra qué entiende OpenAI.
- `./iniciar.sh --microfonos`: lista los micrófonos (para elegir uno en `MICROFONO` del .env).

Después de cada pedido queda grabado en `ultimo_pedido.wav` (sirve para ver qué escuchó).

## Costo
Las charlas de la casa **no se mandan a ningún lado**: la Mac busca "Hola asistente" por su
cuenta con Vosk. Solo cuando Vosk cree escucharla se manda ESE fragmento a OpenAI para
confirmarla (Vosk puede confundir, p. ej., "soy la asistente"). Se paga eso, el pedido, la
respuesta y la voz.
- `./iniciar.sh --prueba-activacion` cuenta cuántas veces se activa y cuántos fragmentos se confirmaron.
  Si se activa sola, subí `UMBRAL_ACTIVACION` (por ejemplo, a 90). Si te cuesta activarla, bajalo (80).

## Probalo (modo texto)
- `poné bohemian rapsodi` (con errores a propósito: la búsqueda los tolera)
- `poné el disco abbey road`
- `pausá` / `siguiente` / `bajá el volumen`
- `poné un temporizador de 10 minutos para la pasta` / `¿cuánto falta?`
- `¿quién ganó la última final de la Champions?` (usa búsqueda web)

## Biblioteca (música y videos)
En el `.env`, `MUSICA_CARPETAS` acepta varias carpetas separadas por `|`:
```
MUSICA_CARPETAS=/Users/yo/Music | /Volumes/Disco externo/Series
```
- El disco o colección es la carpeta que contiene directamente los archivos, a cualquier profundidad.
- Los archivos sueltos en una de esas carpetas van a un disco con el nombre de esa carpeta.
- Si una carpeta no existe al abrir la app, se saltea y se avisa en la Terminal.
- El índice se arma al abrir la app y se actualiza solo cuando agregás o borrás archivos.
