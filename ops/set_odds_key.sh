#!/bin/sh
# Save The Odds API key (the-odds-api.com, free Starter plan) — outside every repo, readable only
# by you — and test it once. Shared location: the bet-analysis tool (pinnacle.mjs) reads the same
# file, so one key serves both. Typed at a hidden prompt: never in shell history, chat or a repo.
set -eu
dir="$HOME/.config/odds-api"
mkdir -p "$dir" && chmod 700 "$dir"
printf 'Paste your Odds API key, then press Return: '
stty -echo; read -r key; stty echo; printf '\n'
[ -n "$key" ] || { echo "No key entered — nothing saved."; exit 1; }
umask 077
printf '%s\n' "$key" > "$dir/key"
# /v4/sports costs 0 credits. The key goes to curl on stdin (a config file), not the command line.
code=$(printf 'url = "https://api.the-odds-api.com/v4/sports?apiKey=%s"\n' "$key" |
       curl -s -o /dev/null -w '%{http_code}' -m 30 -K -)
if [ "$code" = "200" ]; then
  echo "Key saved and working (HTTP 200). Player props can be added on the next build."
else
  echo "Key saved, but the test call returned HTTP $code. A 401 means it was mistyped — run this again."
fi
