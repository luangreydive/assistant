# Hello Assistant

A voice assistant for your home computer. Say **"Hola asistente"** and ask it to play music or a TV show from your own library, set a kitchen timer, or answer a question with a live web search. While it's running, the computer won't go to sleep (the screen still can).

The assistant speaks and understands **Spanish** (Rioplatense by default). The code and the per-version docs are in Spanish too.

## What it does
- **Your local library:** plays any audio or video that [mpv](https://mpv.io) can open, from one or more folders (external drives and network shares too). Fuzzy search handles misheard titles ("bohemian rapsodi" → *Bohemian Rhapsody*).
- **Playback control:** pause, next, previous and volume. Music ducks automatically while it's listening to you.
- **Timers:** "poné un temporizador de 10 minutos para la pasta" / "¿cuánto falta?"
- **Questions:** handled by an OpenAI model, with built-in web search for anything current (news, weather, scores).
- **Keeps the computer awake:** uses `caffeinate` on macOS and `SetThreadExecutionState` on Windows.

## Two versions

| | [`standard/`](standard) | [`high-sierra/`](high-sierra) |
|---|---|---|
| For | Modern macOS (Apple Silicon or Intel) and Windows | Old Intel Macs on **macOS 10.13 High Sierra** (works on Core 2 Duo) |
| Wake phrase | Local [faster-whisper](https://github.com/SYSTRAN/faster-whisper), two-pass check | Local [Vosk](https://alphacephei.com/vosk/) with a closed grammar, confirmed by OpenAI |
| Speech to text (request) | Local Whisper | OpenAI transcription API |
| Voice | Local [Piper](https://github.com/OHF-Voice/piper1-gpl) | OpenAI TTS |
| Brain and web search | OpenAI (Responses API) | OpenAI (Responses API) |
| Player | mpv (latest) | mpv 0.33.1 (last build for 10.12+) |
| Python | 3.12 via [uv](https://github.com/astral-sh/uv) | 3.12.10 from python.org (last 3.12 installer that runs on 10.13) |

**Why a separate High Sierra version?** `onnxruntime`, which Piper and Silero VAD depend on, was never released for macOS 10.13. Recent `ctranslate2`, `av`, mpv and the uv-managed Python builds all require macOS 10.15 or newer, and NumPy ≥ 2.4 requires SSE4.2, which Core 2 CPUs don't have. The High Sierra version replaces those components and installs only prebuilt wheels, so nothing is compiled on the old machine.

## Quick start (macOS)
```bash
git clone https://github.com/luangreydive/assistant.git
cd assistant/standard        # or: cd assistant/high-sierra
./iniciar.sh
```
On the first run, `iniciar.sh` downloads mpv, sets up Python and the dependencies, and creates a `.env` from `.env.example`. Fill in:
- `OPENAI_API_KEY`
- `MUSICA_CARPETAS`: one or more library folders, separated by `|`.

Then run `./iniciar.sh` again.

Useful flags:
- `--texto`: type instead of talking.
- `--prueba-activacion`: count wake-phrase activations to measure false positives.
- `--microfonos`: list input devices.
- `--debug`: verbose logging.
- `--probar-microfono` (High Sierra only): record 5 s, play it back and show what was understood.

For Windows, see [`standard/README.md`](standard/README.md).

## Cost and privacy
- **Standard:** listening, the wake phrase, transcription and the voice all run locally. Only your request text goes to OpenAI.
- **High Sierra:** the wake phrase is detected **on the machine** with Vosk, so background conversation is never sent anywhere. Only when Vosk thinks it heard "Hola asistente" is that one snippet sent to OpenAI, to confirm the phrase and transcribe the request. The answer comes back as OpenAI TTS.

Your `.env` (API key, folders) stays local and is git-ignored.

## Configuration
Everything lives in `.env`; see each version's `.env.example`. Highlights:
- Model and reasoning effort: `OPENAI_MODELO`, `OPENAI_ESFUERZO`.
- Wake phrase and strictness: `FRASE_ACTIVACION` or `FRASE_ACTIVACION_LOCAL`, plus `UMBRAL_ACTIVACION`.
- Optional location for local web results: `UBICACION_PAIS`, `UBICACION_CIUDAD`, `ZONA_HORARIA`.
- High Sierra:
  - `SERVIDOR_MUSICA` auto-mounts library folders shared by another Mac on your network.
  - `STT_MODELO`, `TTS_MODELO`, `TTS_VOZ` and `TTS_INSTRUCCIONES` choose the OpenAI models and voice.

## Credits
Built on [mpv](https://mpv.io), [Vosk](https://alphacephei.com/vosk/), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Piper](https://github.com/OHF-Voice/piper1-gpl), [py-webrtcvad](https://github.com/wiseman/py-webrtcvad), [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), [watchdog](https://github.com/gorakhargosh/watchdog), [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) and the [OpenAI API](https://platform.openai.com).
