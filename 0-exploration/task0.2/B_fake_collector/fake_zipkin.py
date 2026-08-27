#!/usr/bin/env python3
"""Collector Zipkin finto: accetta POST /api/v2/spans, salva il JSON, risponde 202.
Serve solo al task 0.2 per vedere COSA rt-app manda quando qualcuno ascolta."""
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer

T0 = time.time()
OUT = sys.argv[1] if len(sys.argv) > 1 else "spans.json"
batches = []

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n)
        self.send_response(202); self.end_headers()
        spans = json.loads(body)
        batches.append({"t_rel": round(time.time() - T0, 3), "spans": spans})
        print(f"[{time.time()-T0:6.2f}] POST {self.path}  {n} byte  "
              f"{len(spans)} span: {[s.get('name') for s in spans]}", flush=True)
        with open(OUT, "w") as f:
            json.dump(batches, f, indent=2)
    def log_message(self, *a):  # silenzia il log di default
        pass

HTTPServer(("127.0.0.1", 9411), H).serve_forever()
