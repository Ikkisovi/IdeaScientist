"""Loopback LLM bridge for the IdeaScientist harness (chat/completions in).

  python3 -I llm_bridge.py <port> <usage.jsonl> <config.json>

config.json:
  {"mode": "chat" | "responses",
   "upstreams": [{"provider": "<Pi models.json provider>", "base": "<url, default: provider baseUrl>"}, ...],  # round-robin
   "drop": ["chat_template_kwargs", ...],          # request fields the upstream rejects
   "session_header": "x-opencode-session"}         # optional, stable per conversation

Credentials are resolved once from ~/.pi/agent/models.json (literal or "!command") and
never logged. "responses" mode translates chat messages/tools <-> the OpenAI Responses
API (non-streaming). Usage is logged per call.
"""
import hashlib, itertools, json, os, subprocess, sys, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, LOG_PATH, CFG = int(sys.argv[1]), sys.argv[2], json.load(open(sys.argv[3]))
PROV = json.load(open(os.path.expanduser('~/.pi/agent/models.json')))['providers']


def _key(provider):
    k = PROV[provider].get('apiKey', '')
    if k.startswith('!'):
        return subprocess.run(k[1:], shell=True, capture_output=True, text=True).stdout.strip()
    if k.startswith('$'):
        return os.environ.get(k[1:], '')
    return k


UP = [((u.get('base') or PROV[u['provider']]['baseUrl']).rstrip('/'), _key(u['provider']), u['provider'])
      for u in CFG['upstreams']]
RR = itertools.cycle(range(len(UP)))
RR_LOCK, LOG_LOCK = threading.Lock(), threading.Lock()
LOG = open(LOG_PATH, 'a', buffering=1)


# ==================== chat <-> responses ====================

def _text(content):
    if isinstance(content, list):
        return ''.join(p.get('text', '') for p in content if isinstance(p, dict))
    return content or ''


def chat_to_responses(req):
    items = []
    for m in req.get('messages', []):
        role = m.get('role')
        if role == 'tool':
            items.append({'type': 'function_call_output', 'call_id': m.get('tool_call_id'),
                          'output': _text(m.get('content'))})
        elif role == 'assistant':
            if _text(m.get('content')):
                items.append({'role': 'assistant', 'content': _text(m.get('content'))})
            for tc in m.get('tool_calls') or []:
                f = tc.get('function', {})
                items.append({'type': 'function_call', 'call_id': tc.get('id'), 'name': f.get('name'),
                              'arguments': f.get('arguments') or '{}'})
        else:
            items.append({'role': 'system' if role in ('system', 'developer') else 'user',
                          'content': _text(m.get('content'))})
    out = {'model': req['model'], 'input': items, 'store': False}
    mt = req.get('max_tokens') or req.get('max_completion_tokens')
    if mt:
        out['max_output_tokens'] = int(mt)
    if 'temperature' in req:
        out['temperature'] = req['temperature']
    if req.get('tools'):
        out['tools'] = [{'type': 'function', 'name': t['function']['name'],
                         'description': t['function'].get('description', ''),
                         'parameters': t['function'].get('parameters', {'type': 'object'})}
                        for t in req['tools'] if t.get('type') == 'function']
    if isinstance(req.get('tool_choice'), str):
        out['tool_choice'] = req['tool_choice']
    return out


def responses_to_chat(resp, model):
    text, calls, reasoning = [], [], []
    for it in resp.get('output') or []:
        t = it.get('type')
        if t == 'message':
            text += [c.get('text', '') for c in it.get('content') or [] if c.get('type') in ('output_text', 'text')]
        elif t == 'function_call':
            calls.append({'id': it.get('call_id') or it.get('id'), 'type': 'function',
                          'function': {'name': it.get('name'), 'arguments': it.get('arguments') or '{}'}})
        elif t == 'reasoning':
            reasoning += [s.get('text', '') for s in it.get('summary') or []]
    msg = {'role': 'assistant', 'content': ''.join(text) or None}
    if calls:
        msg['tool_calls'] = calls
    if reasoning:
        msg['reasoning_content'] = '\n'.join(reasoning)
    finish = 'tool_calls' if calls else ('length' if resp.get('status') == 'incomplete' else 'stop')
    u = resp.get('usage') or {}
    return {'id': resp.get('id'), 'object': 'chat.completion', 'created': int(time.time()), 'model': model,
            'choices': [{'index': 0, 'message': msg, 'finish_reason': finish}],
            'usage': {'prompt_tokens': u.get('input_tokens', 0), 'completion_tokens': u.get('output_tokens', 0),
                      'total_tokens': u.get('total_tokens', 0),
                      'completion_tokens_details': {'reasoning_tokens': (u.get('output_tokens_details') or {}).get('reasoning_tokens', 0)}}}


# ==================== server ====================

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        req = json.loads(self.rfile.read(n) or b'{}')
        for f in CFG.get('drop', []):
            req.pop(f, None)
        req.pop('stream', None); req.pop('stream_options', None)
        with RR_LOCK:
            base, key, prov = UP[next(RR)]
        hdr = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key,
               'User-Agent': 'OpenAI/Python 1.99.0'}
        if CFG.get('session_header'):
            first = json.dumps(req.get('messages', [])[:2], sort_keys=True)
            hdr[CFG['session_header']] = hashlib.sha256(first.encode()).hexdigest()[:32]
        if CFG['mode'] == 'responses':
            url, body = base + '/responses', chat_to_responses(req)
        else:
            url, body = base + '/chat/completions', req
        t0 = time.time()
        retries = 0
        for attempt in range(8):  # back off on rate limits / transient upstream errors
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr),
                                            timeout=900) as r:
                    code, data = r.status, r.read()
            except urllib.error.HTTPError as e:
                code, data = e.code, e.read()
            except Exception as e:  # network error -> 502 so the harness retries
                code, data = 502, json.dumps({'error': {'message': str(e)}}).encode()
            if code not in (429, 500, 502, 503, 504) or attempt == 7:
                break
            retries += 1
            time.sleep(min(60, 2 ** (attempt + 1)))
            if len(UP) > 1:  # try the other upstream next
                with RR_LOCK:
                    base, key, prov = UP[next(RR)]
                hdr['Authorization'] = 'Bearer ' + key
                url = base + ('/responses' if CFG['mode'] == 'responses' else '/chat/completions')
        if code == 200 and CFG['mode'] == 'responses':
            data = json.dumps(responses_to_chat(json.loads(data), req.get('model'))).encode()
        usage = err = None
        try:
            usage = json.loads(data).get('usage') if code == 200 else None
        except Exception:
            pass
        if code >= 400:
            err = data[:400].decode('utf-8', 'replace')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        with LOG_LOCK:
            LOG.write(json.dumps({'t': time.time(), 'upstream': prov, 'status': code,
                                  'secs': round(time.time() - t0, 2), 'model': req.get('model'),
                                  'usage': usage, 'err': err, 'retries': retries}) + '\n')


ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
