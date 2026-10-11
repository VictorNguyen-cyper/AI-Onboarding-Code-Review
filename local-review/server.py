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
MAX_ATTEMPTS = 2

LANGS = {
    "en": "English",
    "zh-Hant": "Traditional Chinese (繁體中文)",
    "vi": "Vietnamese (Tiếng Việt)",
}

PROMPT = """You are a code reviewer. Read the source code below and judge it against the REQUIREMENTS and the CHECKLIST (criteria C01–C12).

Report:
- strengths: what the code does well.
- weaknesses: problems found. Set "criterion" to the checklist code it relates to (C01–C12), or "other" if none fits.
- criteria: one entry for each of C01–C12 with answer Yes, No or Insufficient information.

Rules:
- Never quote secret values, passwords or connection strings. Record the location only.
- Do not invent locations. "location" must be a file (and line or function) that exists in the input.
- If the input is not enough to assess something, say so. Do not guess.
- Do not rewrite or fix the source code.
- Be concise: at most 8 strengths and 10 weaknesses, each detail 1-2 sentences.

Output language: write summary, title, detail and open_questions in {lang}.
Keep in English: criterion codes, Yes / No / Insufficient information, High / Medium / Low, file paths, code identifiers.

Answer with JSON only, matching the given schema."""

CODES = [f"C{i:02d}" for i in range(1, 13)]
ANSWERS = ["Yes", "No", "Insufficient information"]
SEVERITIES = ["High", "Medium", "Low"]


def _item(extra):
    props = {"title": {"type": "string"}, "detail": {"type": "string"}, "location": {"type": "string"}}
    props.update(extra)
    return {"type": "object", "properties": props, "required": list(props)}


SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": _item({})},
        "weaknesses": {"type": "array", "items": _item({
            "severity": {"type": "string", "enum": SEVERITIES},
            "criterion": {"type": "string", "enum": CODES + ["other"]},
        })},
        "criteria": {"type": "array", "items": {
            "type": "object",
            "properties": {"code": {"type": "string", "enum": CODES},
                           "answer": {"type": "string", "enum": ANSWERS}},
            "required": ["code", "answer"]}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "strengths", "weaknesses", "criteria", "open_questions"],
}


def validate(data):
    """Return the result if it matches SCHEMA's shape, else raise ValueError."""
    def strs(d, keys):
        return {k: str(d[k]) for k in keys}
    try:
        out = {
            "summary": str(data["summary"]),
            "strengths": [strs(x, ["title", "detail", "location"]) for x in data["strengths"]],
            "weaknesses": [],
            "criteria": [],
            "open_questions": [str(q) for q in data["open_questions"]],
        }
        for x in data["weaknesses"]:
            w = strs(x, ["title", "detail", "location", "severity", "criterion"])
            if w["severity"] not in SEVERITIES or w["criterion"] not in CODES + ["other"]:
                raise ValueError("bad enum")
            out["weaknesses"].append(w)
        for x in data["criteria"]:
            c = strs(x, ["code", "answer"])
            if c["code"] not in CODES or c["answer"] not in ANSWERS:
                raise ValueError("bad enum")
            out["criteria"].append(c)
    except (KeyError, TypeError) as e:
        raise ValueError(f"bad shape: {e}")
    return out


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

        messages = build_messages(lang, str(req.get("requirements", "")), files)
        try:
            up = self._chat(model, messages)
        except (urllib.error.URLError, OSError) as e:
            return self._send(502, json.dumps({"error": f"Cannot reach Ollama: {e}"}))

        # Response is NDJSON events: progress, retry, then one result or error.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for attempt in range(MAX_ATTEMPTS):
                if attempt:
                    self._event({"type": "retry"})
                    up = self._chat(model, messages)
                try:
                    self._event({"type": "result", "data": validate(json.loads(self._collect(up)))})
                    return
                except ValueError as e:  # includes json.JSONDecodeError
                    last = str(e)
            self._event({"type": "error", "message": f"The model did not return a valid review ({last}). Try again or use a larger model."})
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser closed the tab; stop generating
        except (urllib.error.URLError, OSError) as e:
            self._event({"type": "error", "message": f"Ollama error: {e}"})

    def _chat(self, model, messages):
        body = json.dumps({
            "model": model, "stream": True, "format": SCHEMA, "messages": messages,
            "options": {"num_ctx": NUM_CTX, "temperature": 0.1},
        }).encode()
        return urllib.request.urlopen(urllib.request.Request(
            self.ollama + "/api/chat", body, {"Content-Type": "application/json"}), timeout=600)

    def _event(self, obj):
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
        self.wfile.flush()

    def _collect(self, up):
        """Read Ollama's stream to the end, sending progress events; return the full text."""
        text = ""
        try:
            for line in up:
                chunk = json.loads(line)
                if "error" in chunk:
                    raise ValueError(f"Ollama: {chunk['error']}")
                text += chunk.get("message", {}).get("content", "")
                self._event({"type": "progress", "chars": len(text)})
        finally:
            up.close()
        return text


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
