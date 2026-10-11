#!/usr/bin/env python3
"""Local AI code review web app. Runs a model through Ollama on this machine.

Usage: python3 local-review/server.py [--port 8765] [--ollama http://127.0.0.1:11434]
Nothing leaves this computer: the server only listens on 127.0.0.1 and only talks to Ollama.
"""
import argparse
import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKLIST = HERE.parent / "checklist.md"
MAX_BODY = 8 * 1024 * 1024
NUM_CTX = 16384

LANGS = {
    "en": "English",
    "zh-Hant": "Traditional Chinese (繁體中文)",
    "vi": "Vietnamese (Tiếng Việt)",
}

PROMPT = """You are a code reviewer. Review the source code below against exactly the 12 criteria C01–C12 in the CHECKLIST, comparing it with the REQUIREMENTS.

Rules:
- Review only against the 12 criteria. No general comments on naming or formatting.
- Never quote secret values, passwords or connection strings. Record the location only.
- Do not invent locations. Every location must be a file and line that exists in the input.
- If the input is not enough to assess a criterion, answer "Insufficient information" and say what is missing. Do not guess.
- Do not rewrite or fix the source code.

Output language: write all headings and prose in {lang}.
Keep in English: criterion codes, Yes / No / Insufficient information, High / Medium / Low, file paths, code identifiers.

Output format (Markdown):

## Overview by criterion
| Code | Answer | Findings |
| --- | --- | --- |
(12 rows C01–C12)

## Findings
- Criterion: <code>
  Location: <file:line or function>
  Severity: High / Medium / Low
  Description: <1-2 sentences>
(or "No findings")

## Open questions
(or "None")

## Plain-language summary
Short sentences for a non-programmer: what the code does, and the main concerns."""


def build_messages(lang, requirements, files):
    checklist = CHECKLIST.read_text(encoding="utf-8") if CHECKLIST.exists() else "(checklist.md not found)"
    parts = [
        "===== CHECKLIST =====", checklist,
        "===== REQUIREMENTS =====", requirements or "(none provided)",
        "===== FILE LIST =====", "\n".join(f["path"] for f in files),
    ]
    for f in files:
        parts += [f"===== FILE: {f['path']} =====", f["content"]]
    system = PROMPT.format(lang=LANGS[lang])
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(parts)}]


class Handler(BaseHTTPRequestHandler):
    ollama = "http://127.0.0.1:11434"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/models":
            try:
                with urllib.request.urlopen(self.ollama + "/api/tags", timeout=5) as r:
                    names = [m["name"] for m in json.load(r).get("models", [])]
                self._send(200, json.dumps({"models": names}))
            except (urllib.error.URLError, OSError):
                self._send(503, json.dumps({"error": "Ollama is not running. Start it with: ollama serve"}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/api/review":
            return self._send(404, json.dumps({"error": "not found"}))
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            return self._send(413, json.dumps({"error": "Input larger than 8 MB"}))
        try:
            req = json.loads(self.rfile.read(length))
            model, lang = req["model"], req.get("lang", "en")
            files = [{"path": str(f["path"]), "content": str(f["content"])} for f in req["files"]]
            if lang not in LANGS or not files:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self._send(400, json.dumps({"error": "Bad request: need model, files and a valid lang"}))

        body = json.dumps({
            "model": model, "stream": True,
            "messages": build_messages(lang, str(req.get("requirements", "")), files),
            "options": {"num_ctx": NUM_CTX, "temperature": 0.1},
        }).encode()
        try:
            up = urllib.request.urlopen(urllib.request.Request(
                self.ollama + "/api/chat", body, {"Content-Type": "application/json"}), timeout=600)
        except (urllib.error.URLError, OSError) as e:
            return self._send(502, json.dumps({"error": f"Cannot reach Ollama: {e}"}))

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for line in up:
                chunk = json.loads(line)
                if "error" in chunk:
                    self.wfile.write(f"\n\n[Ollama error: {chunk['error']}]".encode())
                    break
                self.wfile.write(chunk.get("message", {}).get("content", "").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser closed the tab; stop generating
        finally:
            up.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ollama", default=Handler.ollama)
    args = ap.parse_args()
    Handler.ollama = args.ollama.rstrip("/")
    print(f"Local AI review: http://127.0.0.1:{args.port}  (Ollama: {Handler.ollama})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
