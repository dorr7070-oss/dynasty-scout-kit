#!/bin/sh
# Save the CollegeFootballData.com API key for ops/cfbd.py — outside the repo, readable
# only by you — and test it once. The key is typed at a hidden prompt, so it never
# lands in shell history, a chat transcript, or a repo file.
set -eu
dir="$HOME/.config/dynasty-scout"
mkdir -p "$dir" && chmod 700 "$dir"
printf 'Paste your CollegeFootballData API key, then press Return: '
stty -echo; read -r key; stty echo; printf '\n'
[ -n "$key" ] || { echo "No key entered — nothing saved."; exit 1; }
umask 077
printf '%s\n' "$key" > "$dir/cfbd_key"
code=$(printf 'Authorization: Bearer %s\n' "$key" | curl -s -o /dev/null -w '%{http_code}' -m 30 -H @- \
  "https://api.collegefootballdata.com/player/search?searchTerm=Jeremiah%20Smith")
if [ "$code" = "200" ]; then
  echo "Key saved and working (HTTP 200). College stats will load on the next refresh."
else
  echo "Key saved, but the test call returned HTTP $code. A 401 means the key was mistyped or isn't activated yet — run this again."
fi
