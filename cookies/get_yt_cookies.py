from playwright.sync_api import sync_playwright
import time
import argparse
import sys

NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"

def save_netscape_cookie(cookies, filename="cookies.txt"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(NETSCAPE_HEADER)
        for c in cookies:
            domain = c.get("domain", "")
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            path = c.get("path", "/")
            secure = "TRUE" if c.get("secure", False) else "FALSE"
            expires = str(int(c.get("expires", 0))) if c.get("expires") else "0"
            name = c.get("name", "")
            value = c.get("value", "")
            line = "\t".join([domain, flag, path, secure, expires, name, value])
            f.write(line + "\n")

def click_reject(page):
    selectors = [
        "text=Rifiuta tutto",
        "text=Rifiuta",
        "text=Reject all",
        "button:has-text('Rifiuta tutto')",
        "button:has_text('Reject all')",
        "button[aria-label='Rifiuta tutto']",
        "button[aria-label]='Reject all']",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'rifiuta')]",
        "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'reject')]"
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn:
                btn.scroll_into_view_if_needed()
                btn.click(timeout=3000)
                return True
        except Exception:
            continue
    return False

def cookie(output_file, browser_name="chromium", headless=True):
    with sync_playwright() as p:
        # Seleziona il browser richiesto
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
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.youtube.com", wait_until="domcontentloaded")
        time.sleep(3)
        clicked = click_reject(page)
        time.sleep(1)
        cookies = context.cookies()
        save_netscape_cookie(cookies, output_file)
        print(f"cookie salvato in: {output_file}")
        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Salva i cookie di YouTube in formato Netscape.")
    parser.add_argument("-o", "--output", default="cookies.txt",
                        help="Nome del file di output (default: cookies.txt)")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"],
                        help="Browser da usare: chromium, firefox, webkit (default: chromium)")
    parser.add_argument("--no-headless", dest="headless", action="store_false",
                        help="Esegui il browser in modalità non-headless (utile per debug)")
    parser.add_argument("--headless", dest="headless", action="store_true",
                        help="Esegui il browser in modalità headless (default)")
    parser.set_defaults(headless=True)
    args = parser.parse_args()
    cookie(args.output, browser_name=args.browser, headless=args.headless)
