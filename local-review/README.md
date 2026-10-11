# Local AI review

A web page that reviews code with an open-source model running on your own machine through [Ollama](https://ollama.com). It is free, works offline after the model is downloaded, and sends no code anywhere.

It is **separate from the research workflow**: the study uses Gemini for Tier 3 (`ai-review.md`) and must keep one model for the whole project. Do not paste results from this tool into `review-<feature>.md`.

## Setup (once)

```bash
brew install ollama
ollama serve &                    # or open the Ollama app
ollama pull qwen2.5-coder:7b      # about 4.7 GB; fits a 16 GB Mac
```

## Run

```bash
python3 local-review/server.py    # then open http://127.0.0.1:8765
```

No Python packages are needed. The server listens on 127.0.0.1 only.

## Notes

- The review uses the 12 criteria in `../checklist.md`.
- Secret files (`.env`, `*.pem`, `*.key`…) are sent by name only, as in `review.sh`.
- Context is capped at 16k tokens (`NUM_CTX` in `server.py`). A large folder will be truncated by the model; review a few files at a time.
- A 7B model is clearly weaker than Gemini Pro. Treat its findings as hints, not verdicts.
