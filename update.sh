#!/bin/sh
# Mac/Linux shortcut: same as `python3 update.py` (pulls framework updates first)
cd "$(dirname "$0")" && exec python3 update.py "$@"
