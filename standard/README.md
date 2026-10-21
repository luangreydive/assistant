# Hello Assistant

Asistente de voz para Mac y Windows. Mientras está abierta, la compu no se duerme (la pantalla sí puede apagarse).
Todo corre local salvo el LLM de OpenAI (GPT-6 Luna), que también hace las búsquedas web.

## Estado
- [x] Etapa 1: base por texto (no dormir, índice de música, reproductor, temporizadores, LLM + búsqueda web)
- [x] Etapa 2: voz ("hola asistente" en dos pasos con Whisper local, respuestas con Piper)
- [ ] Etapa 3: ventana de estado
- [ ] Etapa 4: empaquetado .app / .exe

## Instalación y uso (Mac)
```bash
cd hello-assistant/standard
./iniciar.sh
```
La primera vez baja mpv a `bin/`, crea el entorno de Python e instala las dependencias.
Si no existe `.env`, lo crea a partir de `.env.example` para que lo completes.

## Instalación (Windows)
1. Instalá Python 3.12 desde python.org (marcá "Add to PATH").
2. Descargá mpv para Windows y copiá `mpv.exe` a la carpeta `bin\` del proyecto (o poné su ruta en `MPV_RUTA`).
3. En la carpeta del proyecto:
```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m hello_assistant
```

## Uso por voz
`./iniciar.sh` abre en modo voz. Decí **"Hola asistente"**, esperá el bip y hacé tu pedido.
También podés decirlo de corrido: "Hola asistente, poné el disco de Pink Floyd".

Otros modos:
- `./iniciar.sh --texto` — por texto, sin micrófono.
- `./iniciar.sh --prueba-activacion` — solo cuenta activaciones (para medir falsos positivos).
- `./iniciar.sh --debug` — muestra todo lo que transcribe.
- `./iniciar.sh --microfonos` — lista los micrófonos (para elegir uno en `MICROFONO` del .env).

La primera vez descarga los modelos de voz (~750 MB) a la carpeta `models/`. Después todo funciona sin internet salvo OpenAI.
macOS va a pedir permiso de micrófono para la Terminal: aceptalo.

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
- El disco/colección es la carpeta que contiene directamente los archivos, a cualquier profundidad
  (las carpetas intermedias, p. ej. una por usuario o fuente de descarga, no se indexan).
- Archivos sueltos en una de esas carpetas van a un disco con el nombre de esa carpeta.
- Si una carpeta no existe al abrir la app (p. ej. un disco externo desconectado), se saltea y se avisa en la Terminal.
- Cualquier formato de audio o video que reproduzca mpv.
- El índice se arma al abrir la app y se actualiza solo cuando agregás o borrás archivos.
- La vieja `MUSICA_CARPETA` (una sola carpeta) sigue funcionando.
