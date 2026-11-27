# Greek Lexicon API

A FastAPI backend service and web interface for word-by-word lexical analysis of Koine Greek New Testament passages. Given a Bible reference, the service retrieves the Greek text and uses an LLM to break down every word with its lemma, Strong's concordance number, primary English translation, and historical lexicon alternatives (drawing from LSJ, Thayer, and Donnegan).

## Features

- **Word-by-Word Lexical Parsing:** Analyzes every Greek word in sequence, preserving word order and original Greek text.
- **Historical Lexicon Alternatives:** Generates 15+ alternative English glosses per word based on classical and Koine Greek reference works.
- **Reference Normalization:** Automatically formats shorthand verse inputs (e.g., `john1:1` -> `John 1:1`).
- **Offline Demo Support & External Fallback:** Includes built-in offline passages (such as John 1:1, John 3:16, Romans 8:28) and fetches additional verses via the GetBible Tischendorf API.
- **Response Caching:** Uses in-memory LRU caching (`@lru_cache`) to avoid duplicate LLM API calls for repeated verses.
- **Multi-Provider LLM Support:** Automatically routes requests to OpenRouter or Moonshot AI based on the configured API key format.
- **Deployment Ready:** Includes configuration files for Railway (`railway.toml`) and Render (`render.yaml`).

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, Pydantic
- **Frontend:** HTML (`index.html`)
- **External APIs:** GetBible v2 API, OpenRouter / Moonshot Chat Completions API

## Getting Started

### Prerequisites

- Python 3.9+
- An API key from [OpenRouter](https://openrouter.ai) (`sk-or-...`) or [Moonshot AI](https://moonshot.cn)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/carelkat/greek-lexicon-api.git
   cd greek-lexicon-api
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set your environment variable:**
   ```bash
   export KIMI_API_KEY="your-api-key-here"
   ```
   *(On Windows PowerShell: `$env:KIMI_API_KEY="your-api-key-here"`)*

4. **Run the server:**
   ```bash
   python app.py
   ```
   The API will be available at `http://localhost:8000`.

## API Endpoints

### `POST /api/analyze`
Fetches the Greek text for a given Bible reference and returns a word-by-word lexical breakdown.

**Request Body:**
```json
{
  "reference": "John 1:1"
}
```

**Example Response:**
```json
{
  "text": "Ἐν ἀρχῇ ἦν ὁ λόγος...",
  "reference": "John 1:1",
  "analysis": [
    {
      "word": "Ἐν",
      "strong": "G1722",
      "lemma": "ἐν",
      "translation": "in",
      "alternatives": ["within", "by", "with", "among", "..."]
    }
  ]
}
```

### `GET /health`
Health check endpoint returning `{"status": "ok"}`.

## Roadmap & Planned Improvements

- [ ] Expand reference normalization to handle numbered books (e.g., `1 John 1:1`) and multi-verse ranges.
- [ ] Enforce strict Pydantic schema validation and automatic retries on LLM JSON responses.
- [ ] Replace in-memory caching with persistent database storage (SQLite / PostgreSQL).
- [ ] Add comprehensive unit and integration tests using `pytest`.
- [ ] Enhance the web frontend (`index.html`) with interactive word inspection and Strong's number filtering.
