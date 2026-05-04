"""CLI для Docker HEALTHCHECK: GET /healthz (Postgres + Telegram), код выхода 0/1."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> None:
    port_raw = os.environ.get("HEALTHCHECK_PORT", "8080").strip()
    try:
        port = int(port_raw)
    except ValueError:
        print("HEALTHCHECK_PORT is not an integer", file=sys.stderr)
        sys.exit(1)

    if port <= 0:
        # HTTP health отключён в конфиге — не считаем контейнер нездоровым по этому probe.
        sys.exit(0)

    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        print(f"healthcheck request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if data.get("status") == "healthy" and data.get("postgres_ok") and data.get("telegram_ok"):
        sys.exit(0)

    print(json.dumps(data, ensure_ascii=False), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
