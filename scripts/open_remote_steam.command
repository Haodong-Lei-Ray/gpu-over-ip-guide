#!/bin/bash
set -e

repo="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

for python in python3.13 python3; do
    if command -v "$python" >/dev/null && "$python" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        exec "$python" "$repo/scripts/open_remote_steam.py" "$@"
    fi
done

echo '需要 Python 3.10 或更新版本及 Tk。可运行 brew install python-tk@3.13。' >&2
exit 1
