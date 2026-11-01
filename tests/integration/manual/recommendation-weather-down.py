# Run from the repo root: docker compose run --rm --no-deps -T recommendation python - < tests/integration/manual/recommendation-weather-down.py
# Starts six throwaway Recommendation servers whose weather API is refused, slow, garbage, HTTP 500, the wrong shape, or unresolvable; expects 200 with songs every time.
import os, subprocess, sys, time, threading, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as HTTPServer

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(10)
        if self.path.startswith("/garbage"):
            self.send_response(200); self.end_headers(); self.wfile.write(b"not json at all"); return
        if self.path.startswith("/err500"):
            self.send_response(500); self.end_headers(); return
        if self.path.startswith("/weird"):
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"current":{"weather_code":"x"}}'); return
        self.send_response(200); self.end_headers()
srv = HTTPServer(("127.0.0.1", 9100), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
cases = [("refused", "http://127.0.0.1:1/x"), ("slow (10s, timeout 2s)", "http://127.0.0.1:9100/slow"),
         ("garbage body", "http://127.0.0.1:9100/garbage"), ("HTTP 500", "http://127.0.0.1:9100/err500"),
         ("wrong shape", "http://127.0.0.1:9100/weird"), ("DNS fails", "http://no-such-host.invalid/x")]
procs = []
for i, (_, url) in enumerate(cases):
    env = dict(os.environ, CATALOGUE_MODE="stub", WEATHER_MODE="open-meteo", WEATHER_URL=url, PORT=str(9200 + i))
    procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", "recommendation_service.api.main:app", "--port", str(9200 + i), "--log-level", "error"], env=env))
time.sleep(5)
try:
    for i, (name, _) in enumerate(cases):
        t = time.time()
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{9200+i}/recommendations?lat=1.35&lon=103.82&limit=3", timeout=15)
            body = r.read().decode()
            print(f"{name:26} HTTP {r.status} in {time.time()-t:4.1f}s weather_used={'true' in body.split('weather_used')[1][:8]} items={body.count('song_id')}")
        except Exception as e:
            print(f"{name:26} ERROR {e}")
finally:
    for p in procs: p.terminate()
