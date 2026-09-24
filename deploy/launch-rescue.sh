#!/usr/bin/env bash
# Launch on demand. This script does not enable any boot service.
set -euo pipefail
APP_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_ENV=${LAYA_PYTHON_ENV:-$APP_DIR/.venv}
MODEL_DIR=${LAYA_MODEL_DIR:-$APP_DIR/models/Laya}
URL=http://127.0.0.1:8010/rescue.html
if [[ ! -x "$PYTHON_ENV/bin/laya-axera" ]]; then
  printf '未找到 %s/bin/laya-axera，请先安装项目或设置 LAYA_PYTHON_ENV。\n' "$PYTHON_ENV" >&2
  exit 1
fi
if [[ ! -f "$MODEL_DIR/multilingual/model.axmodel" ]]; then
  printf '未找到 multilingual/model.axmodel，请设置 LAYA_MODEL_DIR。\n' >&2
  exit 1
fi
if ! systemctl --user is-active --quiet laya-games; then
  systemd-run --user --unit=laya-games --collect --property=WorkingDirectory="$APP_DIR" \
    "$PYTHON_ENV/bin/laya-axera" serve --model "multilingual=$MODEL_DIR/multilingual" \
    --host 127.0.0.1 --port 8010 --provider AXCLRTExecutionProvider --device 0
fi
"$PYTHON_ENV/bin/python" - "$URL" <<'PY'
import sys
import time
import urllib.error
import urllib.request

for _ in range(50):
    try:
        with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
            if response.status == 200:
                break
    except (OSError, urllib.error.URLError):
        time.sleep(0.2)
else:
    raise SystemExit("页面未就绪，请检查 journalctl --user -u laya-games。")
PY
for browser in chromium chromium-browser; do
  if command -v "$browser" >/dev/null && "$browser" --version >/dev/null 2>&1; then
    exec "$browser" --app="$URL" --no-first-run
  fi
done
if command -v firefox >/dev/null; then
  exec firefox --new-window "$URL"
fi
exec xdg-open "$URL"
