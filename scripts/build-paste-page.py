#!/usr/bin/env python3
"""Build paste-review.html — a box to paste code and get the Tier 3 prompt for Gemini.

Usage (normally through ./qa paste):
    python3 scripts/build-paste-page.py [output path]   # default: paste-review.html

The page is one offline file: it makes no network requests and stores nothing.
It assembles the same prompt as review.sh (the prompt text is read from review.sh,
the criteria from checklist.md) around the code you paste, so you copy it into
gemini.google.com yourself. Section 0 of ai-review.md still applies: mentor approval,
Gemini activity off, and the manual check recorded in log.csv before reviewing.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LANGS = {
    "en": "English",
    "zh-Hant": "Traditional Chinese (繁體中文)",
    "vi": "Vietnamese (Tiếng Việt)",
}


def prompt_from_review_sh():
    """The PROMPT="..." block of review.sh, so the two never drift apart."""
    text = (ROOT / "review.sh").read_text(encoding="utf-8")
    m = re.search(r'^PROMPT="(.*?)"\n\n\{', text, re.S | re.M)
    if not m:
        sys.exit("Could not find the PROMPT block in review.sh.")
    return m.group(1).replace('\\"', '"')


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paste code for review</title><style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e2dc;--accent:#2457c5;--warn:#8a5a00;--warnbg:#fff4d6;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--card:#1f1f1d;--line:#34332f;--accent:#7aa2f7;--warn:#f2c46b;--warnbg:#2e2615;--bad:#f0817a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,system-ui,sans-serif}
main{max-width:900px;margin:0 auto;padding:32px 16px 64px}h1{font-size:24px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.note{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:12px 14px;font-size:14px;margin-bottom:20px}.note ul{margin:6px 0 0;padding-left:18px}
label{display:block;font-weight:600;margin:18px 0 6px}label small{font-weight:400;color:var(--muted)}
textarea,select,input{width:100%;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.45 ui-monospace,Menlo,monospace}
select{font:15px -apple-system,system-ui,sans-serif;width:auto}textarea{min-height:260px;resize:vertical}#req{min-height:110px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px}
button,a.btn{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:10px 16px;font:600 15px -apple-system,system-ui,sans-serif;cursor:pointer;text-decoration:none}
button.sec{background:var(--card);color:var(--fg);border:1px solid var(--line)}button:disabled{opacity:.5;cursor:default}
.warn{color:var(--bad);font-size:14px;margin-top:8px}.muted{color:var(--muted);font-size:13px}
#out{min-height:160px}
</style></head><body><main>
<h1>Paste code for AI review</h1>
<p class="sub">Tier 3 — builds the review prompt in your browser. Nothing is sent or saved anywhere.</p>
<div class="note"><b>Before you paste</b> (<code>ai-review.md</code> section 0):<ul>
<li>Your mentor has allowed you to send code to Gemini.</li>
<li>Gemini Apps Activity is turned off.</li>
<li>The manual check for this feature is already recorded in <code>log.csv</code>.</li>
<li>The code has no secret values, customer names or internal module names.</li></ul></div>

<label for="lang">Language of the AI's answer</label>
<select id="lang">__LANG_OPTIONS__</select>

<label for="req">Requirements <small>(what the feature must do — not the original prompt)</small></label>
<textarea id="req" placeholder="e.g. A signed-in user can see only their own orders…"></textarea>

<label for="code">Code <small>(one file, or several — start each with a line like <code>// FILE: path/to/file.py</code>)</small></label>
<textarea id="code" placeholder="Paste the code here" spellcheck="false"></textarea>
<div id="secrets" class="warn" hidden></div>

<div class="row">
<button id="build">Build prompt</button>
<button id="copy" class="sec" disabled>Copy</button>
<a class="btn" href="https://gemini.google.com/app" target="_blank" rel="noopener noreferrer">Open Gemini</a>
<span class="muted" id="status"></span>
</div>

<label for="out">Prompt to paste into Gemini</label>
<textarea id="out" readonly placeholder="Click “Build prompt”"></textarea>
<p class="muted">Paste Gemini's answer unedited into <code>review-&lt;feature&gt;.md</code>, then classify the findings by hand (rule A.1).</p>
</main>
<script>
const PROMPT = __PROMPT__;
const CHECKLIST = __CHECKLIST__;
const LANGS = __LANGS__;
const $ = id => document.getElementById(id);
// Obvious secret shapes only — a hint, not a guarantee.
const SECRET = [[/-----BEGIN [A-Z ]*PRIVATE KEY-----/, "a private key"],
  [/\\b(?:AKIA|ASIA)[0-9A-Z]{16}\\b/, "an AWS access key"],
  [/\\b(?:sk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}/, "an API token"],
  [/(?:password|passwd|secret|api[_-]?key|token)\\s*[:=]\\s*["'][^"'\\s]{8,}["']/i, "a hard-coded credential"],
  [/\\b[a-z]+:\\/\\/[^\\s:@\\/]+:[^\\s@\\/]+@/i, "a connection string with a password"]];
function scan() {
  const text = $("code").value, hits = SECRET.filter(([re]) => re.test(text)).map(([, n]) => n);
  $("secrets").hidden = !hits.length;
  $("secrets").textContent = hits.length ? "This looks like it contains " + hits.join(", ") + ". Replace the value with a placeholder before sending (never send secret values)." : "";
}
$("code").addEventListener("input", scan);
$("build").onclick = () => {
  const code = $("code").value.trim(), req = $("req").value.trim();
  if (!code || !req) { $("status").textContent = "Paste both the requirements and the code."; return; }
  const body = /^(\\/\\/|#|<!--)?\\s*FILE:/m.test(code) ? code : "===== FILE: pasted-code =====\\n" + code;
  $("out").value = ["===== INSTRUCTIONS =====", PROMPT.replace("$LANG_NAME", LANGS[$("lang").value]), "",
    "===== CHECKLIST =====", CHECKLIST, "", "===== REQUIREMENTS =====", req, "", "===== CODE =====", body, ""].join("\\n");
  $("copy").disabled = false; $("status").textContent = "Prompt ready (" + $("out").value.length + " characters).";
};
$("copy").onclick = async () => {
  try { await navigator.clipboard.writeText($("out").value); $("status").textContent = "Copied."; }
  catch { $("out").select(); $("status").textContent = "Press Ctrl/Cmd+C to copy."; }
};
</script></body></html>
"""


def build(out):
    options = "".join(f'<option value="{k}">{v}</option>' for k, v in LANGS.items())
    page = (TEMPLATE
            .replace("__LANG_OPTIONS__", options)
            .replace("__PROMPT__", json.dumps(prompt_from_review_sh()).replace("</", "<\\/"))
            .replace("__CHECKLIST__", json.dumps((ROOT / "checklist.md").read_text(encoding="utf-8")).replace("</", "<\\/"))
            .replace("__LANGS__", json.dumps(LANGS)))
    Path(out).write_text(page, encoding="utf-8")
    print(f"Wrote {out} — open it in a browser.")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else ROOT / "paste-review.html")
