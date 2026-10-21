#!/bin/bash
# Prepara todo (solo la primera vez) y abre Hello Assistant. Versión para macOS High Sierra (10.13).
# No usa Homebrew.
set -e
cd "$(dirname "$0")"

# 1) mpv 0.33.1: el último build oficial que funciona en macOS 10.12+ (Intel)
MPV_URL="https://laboratory.stolendata.net/~djinn/mpv_osx/mpv-0.33.1.tar.gz"
MPV_SHA="b2cfa0dd1dfd3d00d360a5ed50919920a2429da84315148fdda4bda886aa8225"
if [ ! -x bin/mpv.app/Contents/MacOS/mpv ]; then
  echo "Descargando mpv 0.33.1..."
  TMP="$(mktemp -d)"
  curl -fL --progress-bar -o "$TMP/mpv.tar.gz" "$MPV_URL"
  if [ "$(shasum -a 256 "$TMP/mpv.tar.gz" | cut -d' ' -f1)" != "$MPV_SHA" ]; then
    echo "La descarga de mpv no coincide con la esperada. Abortando."
    rm -rf "$TMP"
    exit 1
  fi
  mkdir -p bin
  tar xzf "$TMP/mpv.tar.gz" -C bin
  xattr -dr com.apple.quarantine bin/mpv.app 2>/dev/null || true
  rm -rf "$TMP"
fi

# 2) Python 3.12 de python.org (el de uv/Homebrew pide macOS 10.15 o más; este funciona en 10.13)
PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
PY_URL="https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg"
PY_SHA="8373e58da4ea146b3eb1c1f9834f19a319440b6b679b06050b1f9ee3237aa8e4"
if [ ! -x "$PY" ]; then
  echo "Descargando el instalador de Python 3.12..."
  PKG="$HOME/Downloads/python-3.12.10-macos11.pkg"
  curl -fL --progress-bar -o "$PKG" "$PY_URL"
  if [ "$(shasum -a 256 "$PKG" | cut -d' ' -f1)" != "$PY_SHA" ]; then
    echo "La descarga de Python no coincide con la esperada. Abortando."
    rm -f "$PKG"
    exit 1
  fi
  echo "Se abre el instalador de Python: seguí los pasos y después volvé a correr ./iniciar.sh"
  open "$PKG"
  exit 1
fi

# 3) Entorno del proyecto y dependencias (solo paquetes precompilados: no se compila nada)
if [ ! -x .venv/bin/python ]; then
  echo "Creando el entorno del proyecto..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install -q --upgrade pip
fi
.venv/bin/python -m pip install -q --only-binary :all: -r requirements.txt
# vosk (detección local de "Hola asistente"; macOS 10.9+, sin SSE4/AVX) va aparte porque
# depende de srt, que solo existe como código fuente (es Python puro: no se compila nada)
.venv/bin/python -m pip install -q --no-deps vosk==0.3.44 srt==3.5.3

# Modelo de Vosk en español para detectar "Hola asistente" sin internet (~40 MB, solo la primera vez)
VOSK_MODELO=vosk-model-small-es-0.42
VOSK_SHA="09b239888f633ef2f0b4e09736e3d9936acfd810bc65d53fad45261762c6511f"
if [ ! -d "models/$VOSK_MODELO" ]; then
  echo "Descargando el modelo para detectar \"Hola asistente\"..."
  TMP="$(mktemp -d)"
  curl -fL --progress-bar -o "$TMP/m.zip" "https://alphacephei.com/vosk/models/$VOSK_MODELO.zip"
  if [ "$(shasum -a 256 "$TMP/m.zip" | cut -d' ' -f1)" != "$VOSK_SHA" ]; then
    echo "La descarga del modelo no coincide con la esperada. Abortando."
    rm -rf "$TMP"
    exit 1
  fi
  mkdir -p models
  unzip -q "$TMP/m.zip" -d models
  rm -rf "$TMP"
fi

# 4) Configuración
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creé el archivo .env. Completá OPENAI_API_KEY y MUSICA_CARPETAS y volvé a correr ./iniciar.sh"
  open -e .env
  exit 1
fi

# 5) Conectar las carpetas compartidas por red (las de MUSICA_CARPETAS que estén en /Volumes)
leer_env() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/^ *//' -e 's/ *$//' -e 's/^"//' -e 's/"$//'; }
SERVIDOR="$(leer_env SERVIDOR_MUSICA)"
if [ -n "$SERVIDOR" ]; then
  IFS='|' read -ra CARPETAS <<< "$(leer_env MUSICA_CARPETAS)"
  for c in "${CARPETAS[@]}"; do
    c="$(echo "$c" | sed -e 's/^ *//' -e 's/ *$//')"
    case "$c" in /Volumes/*) ;; *) continue ;; esac
    VOL="${c#/Volumes/}"; VOL="${VOL%%/*}"
    [ -d "/Volumes/$VOL" ] && continue
    echo "Conectando la carpeta \"$VOL\" de $SERVIDOR..."
    URL="smb://guest:@$SERVIDOR/$(echo "$VOL" | sed 's/ /%20/g')"
    if osascript -e "mount volume \"$URL\"" >/dev/null 2>&1; then
      for _ in 1 2 3 4 5; do [ -d "/Volumes/$VOL" ] && break; sleep 1; done
    fi
    [ -d "/Volumes/$VOL" ] || echo "  No pude conectarla (¿la otra Mac está prendida, en la misma red y con esa carpeta compartida?). Sigo sin ella."
  done
fi

# Certificados actualizados (los del sistema en High Sierra son viejos)
export SSL_CERT_FILE="${SSL_CERT_FILE:-$(.venv/bin/python -m certifi)}"

exec .venv/bin/python -m hello_assistant "$@"
