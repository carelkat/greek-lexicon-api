from fastapi import FastAPI, HTTPException
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


KIMI_API_KEY = os.getenv("KIMI_API_KEY")


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
    Fetch Greek text using a simple fallback approach
    """
    try:
        ref_parts = parse_reference(reference)
        
        # For demo: Use hardcoded verses for common references
        # In production, you'd integrate with a paid Bible API
        verse_database = {
            "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς τὸν θεόν καὶ θεὸς ἦν ὁ λόγος",
            "John 3:16": "οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν",
            "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσιν τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν",
            "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν",
            "Philippians 2:5": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ",
        }
        
        normalized_ref = reference.strip()
        
        if normalized_ref in verse_database:
            return verse_database[normalized_ref]
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Verse '{reference}' not available. Try: John 1:1, John 3:16, Romans 8:28, Matthew 5:3, or Philippians 2:5"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching verse: {str(e)}"
        )

@app.post("/api/analyze")
async def analyze_verse(request: VerseRequest):
    try:
        greek_text = fetch_greek_text(request.reference)

        response = requests.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {KIMI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "moonshot-v1-128k",
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
            content = content.split('```', 2)[1]
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
from fastapi.middleware.cors import CORSMiddleware
