import httpx
from bs4 import BeautifulSoup

def get_channel_og_matadata(channel_url):
    cookies = {
            "CONSENT": "YES+cb.2021038-17-p0.en+FX+299",
            "SOCS": "CAI",
            }
    headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64;x64) AppleWebKit/537.36 (KHTML, like Geko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "En-US,en,q=0.9",
            }

    with httpx.Client(cookies=cookies, headers=headers, follow_redirects=True, timeout=5) as client:
        resp = client.get(channel_url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    def og(prop):
        tag = soup.find("meta", property=prop)
        return tag["content"] if tag else None

    return {
            "title": og("og:title"),
            "description": og("og:description"),
            "logo": og("og:image"),
        }
