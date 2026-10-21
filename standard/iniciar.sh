#!/bin/zsh
# Prepara todo (solo la primera vez) y abre Hello Assistant. No usa Homebrew.
set -e
cd "$(dirname "$0")"

MPV_VER=v0.41.0

# 1) mpv oficial, autocontenido, dentro de bin/
if [ ! -x bin/mpv.app/Contents/MacOS/mpv ]; then
  echo "Descargando mpv $MPV_VER..."
  if [ "$(uname -m)" = "arm64" ]; then ARQ=macos-15-arm; else ARQ=macos-15-intel; fi
  TMP="$(mktemp -d)"
  curl -fL --progress-bar -o "$TMP/mpv.zip" \
    "https://github.com/mpv-player/mpv/releases/download/$MPV_VER/mpv-$MPV_VER-$ARQ.zip"
  unzip -q "$TMP/mpv.zip" -d "$TMP"
  mkdir -p bin
  tar xzf "$TMP/mpv.tar.gz" -C bin
  xattr -dr com.apple.quarantine bin/mpv.app 2>/dev/null || true
  rm -rf "$TMP"
fi

# 2) uv (instala Python 3.12 aislado para el proyecto)
UV="$(command -v uv || true)"
[ -z "$UV" ] && UV="$HOME/.local/bin/uv"
if [ ! -x "$UV" ]; then
  echo "Instalando uv..."
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi

# 3) Entorno del proyecto y dependencias
if [ ! -x .venv/bin/python ]; then
  echo "Creando el entorno del proyecto..."
  "$UV" venv --python 3.12 .venv
fi
"$UV" pip install -q --python .venv/bin/python -r requirements.txt

# 4) Configuración
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Creé el archivo .env. Completá OPENAI_API_KEY y MUSICA_CARPETA y volvé a correr ./iniciar.sh"
  open -e .env
  exit 1
fi

exec .venv/bin/python -m hello_assistant "$@"
