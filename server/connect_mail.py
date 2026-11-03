"""Run interactively on the Jarvis server under the account maintaining .env."""
import base64
import getpass
import hashlib
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
from dotenv import set_key

ROOT = Path(__file__).resolve().parent
PROVIDERS = {
    "gmail": ("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
              "https://www.googleapis.com/auth/gmail.readonly"),
    "outlook": ("https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                "https://graph.microsoft.com/Mail.Read offline_access"),
}


def oauth(provider, client_id, secret):
    authorize, token_url, scope = PROVIDERS[provider]
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            code = query.get("code", [""])[0]
            valid = secrets.compare_digest(query.get("state", [""])[0], state) and bool(code)
            if valid:
                result["code"] = code
            self.send_response(200 if valid else 400)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Jarvis: authorization received." if valid else b"Jarvis: authorization failed.")

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        host = "127.0.0.1" if provider == "gmail" else "localhost"
        redirect = f"http://{host}:{server.server_port}"
        params = dict(client_id=client_id, response_type="code", redirect_uri=redirect, scope=scope,
                      code_challenge=challenge, code_challenge_method="S256", state=state)
        if provider == "gmail":
            params.update(access_type="offline", prompt="consent")
        webbrowser.open(authorize + "?" + urlencode(params))
        stop = time.monotonic() + 300
        while not result and time.monotonic() < stop:
            server.handle_request()
    if not result:
        raise SystemExit("Authorization timed out")
    data = dict(client_id=client_id, grant_type="authorization_code", code=result["code"],
                redirect_uri=redirect, code_verifier=verifier)
    if secret:
        data["client_secret"] = secret
    response = requests.post(token_url, data=data, timeout=20, allow_redirects=False)
    if response.status_code != 200:
        raise SystemExit(f"OAuth exchange returned HTTP {response.status_code}")
    refresh = response.json().get("refresh_token")
    if not refresh:
        raise SystemExit("Provider did not issue a refresh token")
    return refresh


def main():
    provider = input("Почта (gmail/outlook/yandex): ").strip().lower()
    if provider == "yandex":
        address = input("Адрес Яндекс Почты: ").strip()
        password = getpass.getpass("Пароль приложения Яндекс: ")
        if not address or not password:
            raise SystemExit("Enter address and app password")
        import mail_reader
        mail_reader.recent(provider, password, address=address, limit=1)
        values = {"JARVIS_MAIL_YANDEX_ADDRESS": address, "JARVIS_MAIL_YANDEX": password}
    elif provider in PROVIDERS:
        client_id = input("OAuth Client ID: ").strip()
        secret = getpass.getpass("OAuth Client Secret (Enter если пусто): ")
        prefix = "JARVIS_MAIL_" + provider.upper()
        values = {prefix + "_CLIENT_ID": client_id, prefix + "_CLIENT_SECRET": secret,
                  prefix + "_REFRESH_TOKEN": oauth(provider, client_id, secret)}
    else:
        raise SystemExit("Unknown provider")
    env = ROOT / ".env"
    if not env.is_file():
        raise SystemExit("Run from the existing Jarvis server installation")
    for key, value in values.items():
        set_key(str(env), key, value)
    print("Доступ записан. Перезапусти только задачу JarvisAssistant.")


if __name__ == "__main__":
    main()
