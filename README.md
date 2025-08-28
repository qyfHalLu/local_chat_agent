# SophNet AI Chat Agent

A lightweight, local AI chat web app with streaming responses, multi‑file upload, and quick document/OCR utilities. Frontend is a single HTML file; backend is a small Flask server that proxies model calls and performs document parsing/OCR via SophNet EasyLLM APIs.

---

## TL;DR

- **Run:** `python app.py` → auto-picks a free port (5000–5050) and opens your browser.
- **Frontend:** `templates/index.html` (move the provided `index.html` into a `templates/` folder).
- **Env:** set `OPENAI_API_KEY`, `SOPHNET_PROJECT_ID`, `DOC_PARSE_EASYLLM_ID`, `IMAGE_OCR_EASYLLM_ID`.

---

## Features

- **Streaming chat (SSE) with typing effect**
- **Model picker**: DeepSeek V3.1 (Fast), DeepSeek R1, Kimi‑K2, GLM‑4.5 (incl. “web browsing” variants)
- **Editable system prompt** & **Max Tokens** slider (up to 16384)
- **Multi‑file upload** (PDF/DOCX/XLSX/TXT/PPTX & images). Server auto‑parses:
  - Documents → Markdown text via **Doc Parse** EasyLLM
  - Images → Text via **Image OCR** EasyLLM (with table/HTML options)
- **Reference files in your prompt** using the displayed tag
- **Conversation management**: star, delete, rename (auto from first user msg), **localStorage** persistence on the client

## Tech Stack

- **Backend**: Python, Flask, OpenAI Python SDK (pointing to SophNet Open‑APIs), Requests
- **Frontend**: Vanilla HTML/CSS/JS, Marked.js (Markdown renderer), Font Awesome, Server‑Sent Events (SSE)

## Project Structure

```
.
├─ app.py                # Flask server & API routes
├─ templates/
│  └─ index.html         # Frontend (move your file here)
└─ static/               # (optional) static assets if you split CSS/JS later
```

> If you prefer not to move files, change `home()` to `send_file('index.html')` or init Flask with `Flask(__name__, template_folder='.')`.

## Prerequisites

- Python 3.9+
- A SophNet API key (compatible with OpenAI SDK), plus EasyLLM IDs for Doc Parse & OCR

## Installation

```bash
# 1) Create & activate a venv (recommended)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scriptsctivate

# 2) Install deps
pip install flask python-dotenv openai requests

# 3) Place frontend
mkdir -p templates && mv index.html templates/

# 4) Configure environment (see next section)

# 5) Run
python app.py
```

## Configuration (Environment)

The server loads `~/.openai_env` automatically via `python-dotenv`. Create this file in your HOME directory:

```ini
# ~/.openai_env
OPENAI_API_KEY=sk-xxx

# SophNet Project & EasyLLM (required by doc-parse / image-ocr helpers)
SOPHNET_PROJECT_ID=your_project_id
DOC_PARSE_EASYLLM_ID=your_doc_parse_easylm_id
IMAGE_OCR_EASYLLM_ID=your_image_ocr_easylm_id
```

### Model IDs

The frontend shows friendly names; the backend maps them to actual model IDs:

| UI Name                  | Backend ID                             |
| ------------------------ | -------------------------------------- |
| DeepSeek‑V3.1‑Fast       | `DeepSeek-V3.1-Fast`                   |
| DeepSeek‑V3.1‑Fast (web) | `DeepSeek-V3.1-Fast:your_web_model_id` |
| DeepSeek‑R1              | `DeepSeek-R1-0528`                     |
| DeepSeek‑R1 (web)        | `DeepSeek-R1:your_web_model_id`        |
| Kimi‑K2                  | `Kimi-K2`                              |
| GLM‑4.5                  | `GLM-4.5`                              |

## How It Works

- **/ (GET)** serves the chat UI
- **/upload-multi (POST)** accepts multiple files; documents are sent to **Doc Parse**; images are sent to **Image OCR**; the parsed/recognized text is stored in the in‑memory conversation state
- **/chat (POST)** streams model output (SSE). If your message contains a file tag (e.g., `文件A1B2`), the server injects that file’s content as extra system context
- **/remove-file/<file_id> (DELETE)** removes a file from the current session
- **/conversations (GET)** returns a lightweight list of sessions
- **/conversation/<id> (GET/DELETE)** returns or deletes a session
- **/star/<id> (POST)** toggles star
- **/file/<file_id> (GET)** returns full file content

### Request/Response Examples

**Chat (streaming SSE)**

```http
POST /chat
Content-Type: application/json
{
  "session_id": "session_1711111111",
  "message": "请总结 文件A1B2 的要点并翻译为英文",
  "model": "DeepSeek-V3.1-Fast",
  "system_prompt": "你是专属智能助手…",
  "max_tokens": 2048,
  "file_references": ["<file_id>"]  # optional
}

# Response: text/event-stream

data: {"char":"你"}

data: {"char":"好"}
…
data: {"done": true}
```

**Multi-file upload**

```bash
curl -F "session_id=session_1711111111"      -F "files[]=@/path/to/report.pdf"      -F "files[]=@/path/to/photo.png"      http://127.0.0.1:5000/upload-multi
```

## File Referencing

After uploading, each file displays a **tag** like `文件A1B2`. Mention that tag in your next prompt to attach the file’s content to the conversation context.

## Security & Limits

- Conversations live **in server memory** (Python dict) and **in the browser’s localStorage**; this is a dev‑friendly setup, **not** production‑grade persistence.
- Keys/IDs sit in `~/.openai_env` on your machine.
- Network calls go to SophNet Open‑APIs (`base_url`) and EasyLLM endpoints for parsing/OCR.

## Deploy Tips

- Use a real WSGI server (e.g., `gunicorn -w 2 app:app`) behind Nginx.
- Set `FLASK_ENV=production` and ensure `.openai_env` is present in the runtime user’s HOME.
- Consider external session storage (Redis/Postgres) and proper auth if multi‑user.

## Roadmap

- [ ] Persistent storage for conversations/files
- [ ] Role presets & prompt templates
- [ ] Better file preview (pagination for large docs)
- [ ] Drag‑drop uploads & clipboard image paste

## Troubleshooting

- **Blank page or Jinja error** → ensure `index.html` is under `templates/`.
- **403/401 when parsing/OCR** → check `OPENAI_API_KEY`, project & EasyLLM IDs.
- **Model not found** → verify the selected UI model exists in `SUPPORTED_MODELS`.
- **Slow typing** → reduce the artificial per‑character delay in the server stream.
