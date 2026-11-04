"""啟動本機網頁介面：python -m apps.web"""
import argparse
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from api.app import create_app

HOST = '127.0.0.1'
DEFAULT_PORT = 8642


def _open_browser_when_ready(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url + 'api/health', timeout=1):
                break
        except OSError:
            time.sleep(0.1)
    webbrowser.open(url)


def main(argv=None):
    parser = argparse.ArgumentParser(description='啟動 Chess AI 網頁介面')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--no-browser', action='store_true', help='不自動開啟瀏覽器')
    args = parser.parse_args(argv)

    url = f'http://{HOST}:{args.port}/'
    if not args.no_browser:
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    print(f'網頁介面：{url}')
    # SSE 連線不會自行結束，關閉時最多等 3 秒再強制中斷，之後才停止工作並保存。
    uvicorn.run(create_app(), host=HOST, port=args.port, workers=1, reload=False, timeout_graceful_shutdown=3)


if __name__ == '__main__':
    main()
