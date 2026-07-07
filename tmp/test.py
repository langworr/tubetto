import http.cookiejar
import requests
from bs4 import BeautifulSoup

def load_netscape_cookies(path):
    jar = http.cookiejar.MozillaCookieJar(path)
    jar.load(ignore_discard=True, ignore_expires=True)
    return jar

def get_metadata(url, cookies_path=None):
    session = requests.Session()
    if cookies_path:
        session.cookies = load_netscape_cookies(cookies_path)

    r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    def meta(prop):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        return tag["content"] if tag else None


    return {
            "title": meta("og:title") or (soup.title.string if soup.title else None),
            "description": meta("og:description") or meta("description"),
            "image": meta("og:image"),
            "site_name": meta("og:site_name"),
            "favicon": (soup.find("link", rel="icon") or {}).get("href"),
            }
