from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import json
import os
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class VerseRequest(BaseModel):
    reference: str


KIMI_API_KEY = os.getenv("KIMI_API_KEY") or ""


LEXICON_PROMPT = """You are a lexical analyst for Koine Greek. For each Greek word in the verse (in order), provide:

Output ONLY valid JSON array with NO markdown, NO code blocks, NO backticks:
[{"word":"греческое слово","strong":"G####","lemma":"словарная форма","translation":"primary meaning","alternatives":["meaning1","meaning2",...]}]

Requirements:
- Analyze EVERY word in sequence
- Provide Strong's number for each word
- List at least 15 English alternatives from Liddell & Scott and Donnegan's lexicons
- Output ONLY the JSON array, nothing else"""


def parse_reference(ref: str) -> dict:
    pattern = r'^(\d?\s*[A-Za-z]+)\s+(\d+):(\d+)(?:-(\d+))?$'
    match = re.match(pattern, ref.strip(), re.IGNORECASE)

    if not match:
        raise ValueError("Invalid format. Use: Book Chapter:Verse (e.g., John 1:1)")

    book = match.group(1).strip()
    chapter = match.group(2)
    verse_start = match.group(3)
    verse_end = match.group(4) or verse_start

    return {
        "book": book,
        "chapter": chapter,
        "verse_start": verse_start,
        "verse_end": verse_end
    }


def fetch_greek_text(reference: str) -> str:
    """
    Fetch Greek text with multiple fallback strategies.
    1. Local demo database (fastest, no dependencies)
    2. Public getbible.net SBLGNT (no API key required)
    3. rest.api.bible if BIBLE_API_KEY and BIBLE_ID env vars are set
    """
    # 1) Local/demo lookup (fast, no key required)
    verse_database = {
        "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς τὸν θεόν καὶ θεὸς ἦν ὁ λόγος",
        "John 3:16": "οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν",
        "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσιν τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν",
        "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν",
        "Philippians 2:5": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ",
    }

    normalized = reference.strip()
    if normalized in verse_database:
        return verse_database[normalized]

    # 2) Try to parse the reference for structured fetch
    try:
        parts = parse_reference(reference)
        formatted_ref = f"{parts['book']}+{parts['chapter']}:{parts['verse_start']}"
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Verse '{reference}' not available. Demo verses: {', '.join(verse_database.keys())}")

    # 3) Try public SBLGNT endpoint (getbible.net) — no API key needed
    try:
        url = f"https://getbible.net/v2/sblgnt/{formatted_ref}.json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        verses = []
        for chapter_num, chapter_data in data.get('verses', {}).items():
            for verse_num, verse_data in chapter_data.items():
                verses.append(verse_data.get('text', ''))

        if verses:
            return ' '.join(verses)
    except Exception as e:
        print(f"getbible.net failed for {formatted_ref}: {e}")
        pass

    # 4) Optional: try rest.api.bible if BIBLE_API_KEY and BIBLE_ID are set
    BIBLE_API_KEY = os.getenv("BIBLE_API_KEY") or os.getenv("BIBLE_KEY")
    BIBLE_ID = os.getenv("BIBLE_ID")
    if BIBLE_API_KEY and BIBLE_ID:
        try:
            headers = {"accept": "application/json", "api-key": BIBLE_API_KEY}
            passage_path = f"{parts['book']}%20{parts['chapter']}:{parts['verse_start']}"
            url = f"https://rest.api.bible/v1/bibles/{BIBLE_ID}/passages/{passage_path}"
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            j = r.json()
            if isinstance(j, dict):
                text_parts = []
                def extract_text(obj):
                    if isinstance(obj, str):
                        text_parts.append(obj)
                    elif isinstance(obj, dict):
                        for v in obj.values():
                            extract_text(v)
                    elif isinstance(obj, list):
                        for i in obj:
                            extract_text(i)
                extract_text(j)
                if text_parts:
                    return ' '.join(text_parts)
        except Exception:
            pass

    # 5) Nothing found
    raise HTTPException(status_code=404, detail=f"Verse '{reference}' not available. Demo verses: {', '.join(verse_database.keys())}")

@app.post("/api/analyze")
async def analyze_verse(request: VerseRequest):
    try:
        greek_text = fetch_greek_text(request.reference)

        # Choose API endpoint and model based on key format
        if KIMI_API_KEY.startswith("sk-or-"):
            api_url = "https://openrouter.ai/api/v1/chat/completions"
            model = "gpt-4o-mini"  # example; replace with a supported model for OpenRouter
        else:
            api_url = "https://api.moonshot.cn/v1/chat/completions"
            model = "moonshot-v1-128k"

        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {KIMI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": LEXICON_PROMPT},
                    {"role": "user", "content": f"<verse>{greek_text}</verse>"}
                ],
                "temperature": 0.3
            },
            timeout=60
        )

        response.raise_for_status()
        result = response.json()
        content = result['choices'][0]['message']['content']

        content = content.strip()
        if content.startswith('```'):
            parts = content.split('```', 2)
            if len(parts) >= 2:
                content = parts[1]
                if content.startswith('json'):
                    content = content[4:]
        content = content.strip()

        lexicon_data = json.loads(content)

        return {
            "text": greek_text,
            "reference": request.reference,
            "analysis": lexicon_data
        }

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON from AI: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/")
async def root():
    return {
        "status": "Greek Lexicon API v2.0",
        "info": "Enter any New Testament verse reference"
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
