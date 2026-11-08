#!/usr/bin/env bash
# Installazione senza plugin: copia agenti e comandi in un progetto o globalmente.
#   curl -fsSL https://raw.githubusercontent.com/sjckness/sjckAI-tools/main/install.sh | bash            # progetto corrente
#   curl -fsSL https://raw.githubusercontent.com/sjckness/sjckAI-tools/main/install.sh | bash -s -- -g  # globale (~/.claude)
set -euo pipefail

REPO="${SJCK_REPO:-sjckness/sjckAI-tools}"
REF="${SJCK_REF:-main}"
DEST="./.claude"
[[ "${1:-}" == "-g" || "${1:-}" == "--global" ]] && DEST="$HOME/.claude"

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz -C "$tmp"
root="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d | head -1)"

mkdir -p "$DEST"
abs_dest="$(cd "$DEST" && pwd)"

copy() {  # copia un file; .bak solo se la destinazione esiste e differisce dal contenuto finale
  mkdir -p "$(dirname "$2")"
  local stage; stage="$(mktemp "$tmp/stage.XXXXXX")"
  cp "$1" "$stage"
  # senza plugin ${CLAUDE_PLUGIN_ROOT} non esiste: punta agli script copiati (percorso assoluto)
  if [[ "$2" == *.md ]]; then
    sed "s#\${CLAUDE_PLUGIN_ROOT}/scripts#$abs_dest/sjck-scripts#g" "$stage" > "$stage.out" && mv "$stage.out" "$stage"
  fi
  [[ -e "$2" ]] && ! cmp -s "$stage" "$2" && cp "$2" "$2.bak"
  cp "$stage" "$2"
  rm -f "$stage"
}

for plugin in sjck-graph sjck-onboard; do
  src="$root/$plugin"
  [[ -d "$src" ]] || continue
  for d in agents commands; do
    [[ -d "$src/$d" ]] || continue
    for f in "$src/$d"/*.md; do copy "$f" "$DEST/$d/$(basename "$f")"; done
  done
  if [[ -d "$src/skills" ]]; then
    (cd "$src/skills" && find . -type f) | while read -r f; do
      copy "$src/skills/$f" "$DEST/skills/$f"
    done
  fi
  if [[ -d "$src/scripts" ]]; then
    for f in "$src/scripts"/*; do [[ -f "$f" ]] && copy "$f" "$DEST/sjck-scripts/$(basename "$f")"; done
  fi
  # config/ e' sorella di sjck-scripts: gli script la cercano in HERE/../config
  if [[ -d "$src/config" ]]; then
    for f in "$src/config"/*; do [[ -f "$f" ]] && copy "$f" "$DEST/config/$(basename "$f")"; done
  fi
done

echo "sjck installato in $DEST"
echo "Comandi: /sjck-onboard, /sjck-run <task>, /sjck-status, /sjck-view, /sjck-eval"
