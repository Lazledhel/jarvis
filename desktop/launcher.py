"""Start the Jarvis desktop window with the Android client's TLS trust anchor."""
import argparse
import base64
import io
import wave
import json
from urllib.parse import quote
import os
import ssl
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SERVER = os.getenv("JARVIS_SERVER_URL", "")
LIMIT = 12 * 1024 * 1024
ALLOWED = {"/desktop", "/ask", "/developer/jobs"}


class LocalWake:
    def __init__(self):
        self.models = []
        self.lock = threading.Lock()

    def detect(self, encoded):
        pcm = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(pcm), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError("Expected mono 16 kHz PCM")
            if wav.getnframes() > 128000:
                raise ValueError("Wake sample too long")
            samples = wav.readframes(wav.getnframes())
        from vosk import KaldiRecognizer, Model, SetLogLevel
        with self.lock:
            if not self.models:
                SetLogLevel(-1)
                cache = Path(os.environ["LOCALAPPDATA"]) / "Jarvis" / "wake-models"
                folders = ("vosk-model-small-ru-0.22", "vosk-model-small-en-us-0.15")
                for folder in folders:
                    target = cache / folder
                    if not (target / ".ready").exists():
                        shutil.copytree(Path(os.getenv("JARVIS_WAKE_ASSETS", ROOT / "android/app/src/main/assets")) / folder, target, dirs_exist_ok=True)
                        (target / ".ready").touch()
                try:
                    self.models = [(Model(str(cache / folder)), word)
                                   for folder, word in zip(folders, ("джарвис", "jarvis"))]
                except Exception as error:
                    raise RuntimeError("Cannot load local Vosk models") from error
            for model, word in self.models:
                recognizer = KaldiRecognizer(model, 16000, json.dumps([word, "[unk]"], ensure_ascii=False))
                recognizer.AcceptWaveform(samples)
                if json.loads(recognizer.FinalResult()).get("text") == word:
                    return True
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def run(edge, server_url):
    server_parts = urlsplit(server_url)
    if server_parts.scheme != "https" or not server_parts.hostname or server_parts.username:
        raise ValueError("An HTTPS Jarvis server is required")
    context = ssl.create_default_context(cafile=str(Path(os.getenv("JARVIS_SERVER_CERT", ROOT / "assets/server.crt"))))
    client = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), NoRedirect())

    provision = ROOT / "provision.json"
    token = None
    if server_url.rstrip("/") == SERVER and provision.is_file():
        token = json.loads(provision.read_text(encoding="utf-8-sig")).get("token")
    import secrets
    bootstrap = "/start/" + secrets.token_urlsafe(24)

    wake = LocalWake()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.relay()

        def do_POST(self):
            self.relay()

        def relay(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != origin.removeprefix("http://") or (
                self.headers.get("Origin") not in (None, origin)
            ):
                self.send_error(403)
                return
            if self.command == "GET" and self.path == bootstrap:
                self.send_response(303)
                self.send_header("Location", "/desktop" + ("#provision=" + quote(token, safe="") if token else ""))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            parts = urlsplit(self.path)
            if parts.scheme or parts.netloc or not (
                parts.path in ALLOWED or parts.path.startswith("/dashboard/")
            ):
                self.send_error(404)
                return
            size = self.headers.get("Content-Length", "0")
            if not size.isdecimal() or int(size) > 3000000:
                self.send_error(413)
                return
            body = self.rfile.read(int(size)) if self.command == "POST" else None
            if parts.path == "/dashboard/local/screen":
                if (self.command != "POST" or self.headers.get("Origin") != origin
                        or not token or not secrets.compare_digest(
                            self.headers.get("Authorization", ""), "Bearer " + token)):
                    self.send_error(403)
                    return
                try:
                    from PIL import ImageGrab
                    import ctypes
                    from ctypes import wintypes
                    time.sleep(3)
                    user32 = ctypes.windll.user32
                    user32.GetForegroundWindow.restype = wintypes.HWND
                    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
                    rect = wintypes.RECT()
                    if not user32.GetWindowRect(user32.GetForegroundWindow(), ctypes.byref(rect)):
                        raise OSError("No foreground window")
                    image = ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom),all_screens=True).convert("RGB")
                    image.thumbnail((1600,1100))
                    buffer = io.BytesIO()
                    image.save(buffer,format="JPEG",quality=80)
                    data = json.dumps({"image":base64.b64encode(buffer.getvalue()).decode()}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type","application/json")
                    self.send_header("Cache-Control","no-store")
                    self.send_header("Content-Length",str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (ImportError, OSError, ValueError):
                    self.send_error(503)
                return
            if parts.path in ("/dashboard/wake", "/dashboard/wake-local"):
                if self.command != "POST" or not body or len(body) > 400000:
                    self.send_error(400)
                    return
                try:
                    detected = wake.detect(json.loads(body)["audio"])
                except (ValueError, KeyError, TypeError, EOFError, wave.Error):
                    self.send_error(400)
                    return
                except (ImportError, OSError, RuntimeError):
                    self.send_error(503, "Local Vosk unavailable")
                    return
                data = json.dumps({"wake": detected}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            headers = {name: self.headers[name] for name in ("Authorization", "Content-Type")
                       if name in self.headers}
            request = urllib.request.Request(server_url.rstrip("/") + self.path, data=body,
                                             headers=headers, method=self.command)
            try:
                try:
                    response = client.open(request, timeout=240 if parts.path == "/ask" else 110)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    if response.status == 200 and parts.path.endswith("/live"):
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-Camera-Rotation", response.headers.get("X-Camera-Rotation", "0"))
                        self.send_header("X-Camera-Mode", response.headers.get("X-Camera-Mode", ""))
                        self.end_headers()
                        try:
                            while chunk := response.read1(8192):
                                self.wfile.write(chunk)
                        except (OSError, ValueError):
                            pass
                        return
                    data = response.read(LIMIT + 1)
                    if len(data) > LIMIT:
                        self.send_error(502)
                        return
                    if parts.path == "/desktop" and response.status == 200:
                        data = data.replace(b"<script>", b"<script>\nwindow.jarvisDesktop=true;\nif(location.hash.startsWith('#provision=')){sessionStorage.token=decodeURIComponent(location.hash.slice(11));history.replaceState(null,'',location.pathname)}", 1)
                    self.send_response(response.status)
                    for name in ("Content-Type", "Content-Security-Policy"):
                        if name in response.headers:
                            self.send_header(name, response.headers[name])
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(data)
            except TimeoutError:
                self.send_error(504, "Jarvis server timed out")
            except (OSError, ValueError):
                self.send_error(502, "Jarvis server connection failed")

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as listener:
        profile = Path(os.environ["LOCALAPPDATA"]) / "Jarvis" / "Edge"
        args = [edge, f"--user-data-dir={profile}", "--no-first-run", "--disable-extensions",
                f"--app=http://127.0.0.1:{listener.server_port}{bootstrap}"]
        browser = subprocess.Popen(args)
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        try:
            browser.wait()
        finally:
            listener.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("edge")
    parser.add_argument("--server", default=SERVER)
    args = parser.parse_args()
    run(args.edge, args.server)
