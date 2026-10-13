"""Loopback forwarder: harness -> command-code (OpenAI-compatible).
Injects the credential (resolved once from the Pi models.json command) and an
SDK-like User-Agent (Cloudflare blocks Python-urllib). Logs token usage only."""
import json, os, subprocess, sys, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

P = json.load(open(os.path.expanduser('~/.pi/agent/models.json')))['providers']['command-code']
BASE = P['baseUrl'].rstrip('/')
KEY = subprocess.run(P['apiKey'][1:], shell=True, capture_output=True, text=True).stdout.strip()
LOG = open(sys.argv[2] if len(sys.argv) > 2 else 'cc_proxy_usage.jsonl', 'a', buffering=1)
LOCK = threading.Lock()
# Optional eval mode: argv[3] = extra JSON fields to inject, argv[4] = token allowance
# added to max_tokens for residual reasoning (judge budgets assume a non-reasoning judge).
INJECT = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
ALLOW = int(sys.argv[4]) if len(sys.argv) > 4 else 0

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _fwd(self, method):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else None
        if body is None and 'chunked' in (self.headers.get('Transfer-Encoding') or '').lower():
            parts = []
            while True:
                size = int(self.rfile.readline().strip().split(b';')[0], 16)
                if size == 0:
                    self.rfile.readline(); break
                parts.append(self.rfile.read(size)); self.rfile.readline()
            body = b''.join(parts)
        if body and (INJECT or ALLOW):
            try:
                o = json.loads(body); o.update(INJECT)
                if ALLOW and 'max_tokens' in o: o['max_tokens'] = int(o['max_tokens']) + ALLOW
                body = json.dumps(o).encode()
            except Exception: pass
        path = self.path[3:] if self.path.startswith('/v1') else self.path
        req = urllib.request.Request(BASE + path, data=body, method=method, headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY,
            'User-Agent': 'OpenAI/Python 1.99.0', 'Accept': self.headers.get('Accept', '*/*')})
        t = time.time()
        try:
            r = urllib.request.urlopen(req, timeout=900); code = r.status
        except urllib.error.HTTPError as e:
            r = e; code = e.code
        data = r.read()
        self.send_response(code)
        self.send_header('Content-Type', r.headers.get('Content-Type', 'application/json'))
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
        usage = None
        err = data[:400].decode('utf-8', 'replace') if code >= 400 else None
        try: req_info = {k: (v if k in ('model', 'max_tokens', 'temperature', 'stream') else type(v).__name__)
                         for k, v in json.loads(body).items()} if body else {'empty_body': True, 'hdrs': dict(self.headers)}
        except Exception: req_info = {'unparsed': len(body or b'')}
        try: usage = json.loads(data).get('usage')
        except Exception: pass
        with LOCK:
            LOG.write(json.dumps({'t': time.time(), 'path': path, 'status': code, 'secs': round(time.time() - t, 2),
                                  'model': (json.loads(body).get('model') if body else None), 'usage': usage, 'req': req_info, 'err': err}) + '\n')
    def do_POST(self): self._fwd('POST')
    def do_GET(self): self._fwd('GET')

ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
