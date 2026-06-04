import os
import threading
import time
from urllib.parse import urlparse

import requests


DEFAULT_MIN_INTERVALS = {
    "amazon.in": 2.0,
    "www.ebay.com": 1.5,
    "www.walmart.com": 2.5,
}

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    ),
]

BASE_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


class RequestThrottler:
    def __init__(self, min_intervals=None):
        self.min_intervals = min_intervals or {}
        self._last_request_at = {}
        self._lock = threading.Lock()

    def wait_for_slot(self, host):
        interval = self.min_intervals.get(host, 1.0)
        with self._lock:
            last_ts = self._last_request_at.get(host, 0.0)
            now = time.monotonic()
            wait_time = interval - (now - last_ts)
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request_at[host] = time.monotonic()


throttler = RequestThrottler(DEFAULT_MIN_INTERVALS)
_ua_index = 0
_ua_lock = threading.Lock()


def _next_user_agent():
    global _ua_index
    with _ua_lock:
        value = USER_AGENTS[_ua_index % len(USER_AGENTS)]
        _ua_index += 1
        return value


def build_browser_headers(host, referer=None, extra=None):
    headers = dict(BASE_BROWSER_HEADERS)
    headers["User-Agent"] = _next_user_agent()
    headers["Host"] = host
    if referer:
        headers["Referer"] = referer
    if extra:
        headers.update(extra)
    return headers


def _build_proxies():
    proxy = os.getenv("SCRAPER_PROXY", "").strip()
    http_proxy = os.getenv("SCRAPER_HTTP_PROXY", "").strip()
    https_proxy = os.getenv("SCRAPER_HTTPS_PROXY", "").strip()
    if proxy and not (http_proxy or https_proxy):
        http_proxy = proxy
        https_proxy = proxy
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies or None


def _proxy_for_selenium():
    proxy = os.getenv("SCRAPER_PROXY", "").strip()
    if proxy:
        return proxy
    https_proxy = os.getenv("SCRAPER_HTTPS_PROXY", "").strip()
    if https_proxy:
        return https_proxy
    http_proxy = os.getenv("SCRAPER_HTTP_PROXY", "").strip()
    return http_proxy or None


def throttled_get(url, headers=None, params=None, timeout=15, retries=2):
    host = urlparse(url).netloc
    attempt = 0
    proxies = _build_proxies()

    while True:
        throttler.wait_for_slot(host)
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout, proxies=proxies)
        except requests.RequestException:
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(0.75 * attempt)
            continue

        if response.status_code in (429, 503) and attempt < retries:
            attempt += 1
            time.sleep(1.25 * attempt)
            continue

        return response


def fetch_page_with_selenium(url, wait_seconds=3):
    """
    Optional dynamic-content fallback.
    Returns HTML string or None when Selenium/driver is unavailable.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except Exception:
        return None

    driver = None
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument(f"--user-agent={_next_user_agent()}")
        proxy = _proxy_for_selenium()
        if proxy:
            options.add_argument(f"--proxy-server={proxy}")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(25)
        driver.get(url)
        time.sleep(max(1, wait_seconds))
        return driver.page_source
    except Exception:
        return None
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
