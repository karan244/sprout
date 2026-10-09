#!/usr/bin/env bash
# Sprout launcher: finds Ollama, picks a model, runs the app.
set -u
cd "$(dirname "$0")"

BRIDGE="${LINGOBUDDY_HOST:-http://172.29.192.1:11434}"

if ! curl -s --max-time 4 "$BRIDGE/api/version" >/dev/null 2>&1; then
  echo "[!] Cannot reach Ollama at $BRIDGE"
  echo "    On Windows, start it:"
  echo "      & \"\$env:LOCALAPPDATA\Programs\Ollama\ollama.exe\" serve"
  exit 1
fi

MODEL="${LINGOBUDDY_MODEL:-}"
if [ -z "$MODEL" ]; then
  for candidate in qwen2.5:3b gemma3:4b; do
    if curl -s --max-time 5 "$BRIDGE/api/tags" | grep -q "\"$candidate\""; then
      MODEL="$candidate"; break
    fi
  done
fi

if [ -z "$MODEL" ]; then
  echo "[!] No suitable model found. Pull one:"
  echo "      ollama pull qwen2.5:3b"
  exit 1
fi

echo "[i] Ollama  $BRIDGE"
echo "[i] model   $MODEL"
echo "[i] host    $(uname -srm | cut -c1-58)"
echo

exec env OLLAMA_HOST="$BRIDGE" python3 sprout.py --model "$MODEL" "$@"