"""site/ をローカルプレビューする簡易HTTPサーバ（標準ライブラリのみ）。

    python scripts/serve.py            # http://127.0.0.1:8000
    python scripts/serve.py --port 9000

127.0.0.1 のみバインド（認証機構がないため 0.0.0.0 にはしない）。
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver

import common as C


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(C.SITE_DIR)
    )
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"[serve] {C.SITE_DIR}")
        print(f"[serve] http://127.0.0.1:{args.port}  (Ctrl+C で停止)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[serve] 停止しました")


if __name__ == "__main__":
    main()
