import argparse
import base64
import os
import sys
import time

from playwright.sync_api import sync_playwright

NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"

# Deve essere IDENTICO allo User-Agent (YT_USER_AGENT) usato in
# resolve_channel_metadata() lato Django: se non combacia, Google puo'
# invalidare la sessione dei cookie anche se i valori sono corretti.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def generate_dynamic_socs_cookie() -> str:
    """Genera in tempo reale un valore di cookie SOCS (Protobuf + Base64) valido."""
    current_time_sec = int(time.time())

    ts_bytes = bytearray()
    val = current_time_sec
    while val > 0:
        b = val & 0x7F
        val >>= 7
        if val > 0:
            b |= 0x80
        ts_bytes.append(b)

    sub_msg = bytearray([0x08]) + ts_bytes
    region_info = b"\x0a\x02it\x12\x00"

    proto = (
        bytearray([0x08, 0x01, 0x12, len(sub_msg)])
        + sub_msg
        + bytearray([0x1a, len(region_info)])
        + region_info
    )

    return base64.urlsafe_b64encode(proto).decode("utf-8").rstrip("=")


def fix_pref_value(pref_value: str) -> str:
    """Aggiunge f6=40000 (consenso GDPR accettato) e hl=it a PREF se mancanti."""
    if not pref_value:
        return "f6=40000&hl=it&tz=Europe/Rome"

    parts = pref_value.split("&")
    kv = {}
    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k] = v

    # f6=40000 indica a YouTube che il consenso privacy è confermato
    kv["f6"] = "40000"
    kv["hl"] = "it"
    if "tz" not in kv:
        kv["tz"] = "Europe/Rome"

    return "&".join([f"{k}={v}" for k, v in kv.items()])


def save_netscape_cookie(cookies, filename="cookies.txt"):
    cookies_to_save = list(cookies)
    one_year_later = int(time.time()) + 31536000

    has_pref = False
    for c in cookies_to_save:
        if c.get("name") == "PREF":
            has_pref = True
            c["value"] = fix_pref_value(c.get("value", ""))

    if not has_pref:
        cookies_to_save.append({
            "domain": ".youtube.com",
            "path": "/",
            "secure": True,
            "expires": one_year_later,
            "name": "PREF",
            "value": fix_pref_value(""),
        })

    with open(filename, "w", encoding="utf-8") as f:
        f.write(NETSCAPE_HEADER)
        for c in cookies_to_save:
            domain = c.get("domain", "")
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            exp_val = c.get("expires", 0)
            if not exp_val or exp_val <= 0:
                expires = str(one_year_later)
            else:
                expires = str(int(exp_val))

            name = c.get("name", "")
            value = c.get("value", "")
            line = "\t".join([domain, flag, path, secure, expires, name, value])
            f.write(line + "\n")


def save_http_cookie(cookies, filename="cookies_http.txt"):
    cookie_dict = {c.get("name"): c.get("value") for c in cookies if c.get("name")}

    # Correzione / Generazione del cookie PREF
    current_pref = cookie_dict.get("PREF", "")
    cookie_dict["PREF"] = fix_pref_value(current_pref)

    # Assicuriamo la presenza di SOCS e CONSENT
    if "SOCS" not in cookie_dict:
        cookie_dict["SOCS"] = generate_dynamic_socs_cookie()
    if "CONSENT" not in cookie_dict:
        cookie_dict["CONSENT"] = "YES+cb"

    cookie_pairs = [f"{k}={v}" for k, v in cookie_dict.items()]
    http_header_content = "; ".join(cookie_pairs)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(http_header_content)


def cookie(output_file, browser_name="chromium", headless=True):
    with sync_playwright() as p:
        browser_name = browser_name.lower()
        if browser_name == "chromium":
            browser_launcher = p.chromium
        elif browser_name == "firefox":
            browser_launcher = p.firefox
        elif browser_name == "webkit":
            browser_launcher = p.webkit
        else:
            print(f"Browser non supportato: {browser_name}", file=sys.stderr)
            return

        browser = browser_launcher.launch(headless=headless)
        context = browser.new_context(
            locale="it-IT",
            user_agent=USER_AGENT,
            extra_http_headers={
                "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
            },
        )

        socs_val = generate_dynamic_socs_cookie()
        one_year_later = int(time.time()) + 31536000

        initial_cookies = [
            {
                "name": "SOCS",
                "value": socs_val,
                "domain": ".youtube.com",
                "path": "/",
                "expires": one_year_later,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "CONSENT",
                "value": "YES+cb",
                "domain": ".youtube.com",
                "path": "/",
                "expires": one_year_later,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
            {
                "name": "PREF",
                "value": "f6=40000&hl=it&tz=Europe/Rome",
                "domain": ".youtube.com",
                "path": "/",
                "expires": one_year_later,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
        ]
        context.add_cookies(initial_cookies)

        page = context.new_page()
        page.goto("https://www.youtube.com", wait_until="networkidle")
        time.sleep(2)

        cookies = context.cookies()

        save_netscape_cookie(cookies, output_file)
        print(f"Cookie Netscape salvato in: {output_file}")

        base_name, _ = os.path.splitext(output_file)
        http_output_file = f"{base_name}_http.txt"
        save_http_cookie(cookies, http_output_file)
        print(f"Cookie HTTP salvato in: {http_output_file}")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Salva i cookie di YouTube in formato Netscape e HTTP."
    )
    parser.add_argument(
        "-o",
        "--output",
        default="cookies.txt",
        help="Nome del file di output (default: cookies.txt)",
    )
    parser.add_argument(
        "--browser",
        default="chromium",
        choices=["chromium", "firefox", "webkit"],
        help="Browser da usare: chromium, firefox, webkit (default: chromium)",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Esegui il browser in modalità non-headless (utile per debug)",
    )
    parser.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="Esegui il browser in modalità headless (default)",
    )
    parser.set_defaults(headless=True)
    args = parser.parse_args()

    cookie(args.output, browser_name=args.browser, headless=args.headless)
