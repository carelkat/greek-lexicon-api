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
    Fetch Greek text with API.Bible or fallback to demo verses
    """
    api_bible_key = os.getenv("API_BIBLE_KEY")
    
    # If we have API.Bible key, try to fetch
    if api_bible_key:
        try:
            # SBLGNT Bible ID on API.Bible
            bible_id = "de4e12af7f28f599-02"
            
            # Map book names to codes
            book_codes = {
                "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN",
                "Acts": "ACT", "Romans": "ROM", 
                "1 Corinthians": "1CO", "2 Corinthians": "2CO",
                "Galatians": "GAL", "Ephesians": "EPH", 
                "Philippians": "PHP", "Colossians": "COL",
                "1 Thessalonians": "1TH", "2 Thessalonians": "2TH",
                "1 Timothy": "1TI", "2 Timothy": "2TI",
                "Titus": "TIT", "Philemon": "PHM", "Hebrews": "HEB",
                "James": "JAS", "1 Peter": "1PE", "2 Peter": "2PE",
                "1 John": "1JN", "2 John": "2JN", "3 John": "3JN",
                "Jude": "JUD", "Revelation": "REV"
            }
            
            ref_parts = parse_reference(reference)
            book = ref_parts["book"]
            
            # Get book code
            book_code = book_codes.get(book, book.upper()[:3])
            verse_id = f"{book_code}.{ref_parts['chapter']}.{ref_parts['verse_start']}"
            
            url = f"https://api.scripture.api.bible/v1/bibles/{bible_id}/verses/{verse_id}"
            response = requests.get(
                url,
                headers={"api-key": api_bible_key},
                params={"content-type": "text"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                greek_text = data['data']['content']
                # Remove HTML tags
                import re
                greek_text = re.sub(r'<[^>]+>', '', greek_text).strip()
                return greek_text
                
        except Exception as e:
            print(f"API.Bible error: {e}")
            # Continue to fallback
    
    # Fallback to demo verses
    verse_database = {
        "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς τὸν θεόν καὶ θεὸς ἦν ὁ λόγος",
        "John 3:16": "οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν",
        "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσιν τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν",
        "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν",
        "Philippians 2:5": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ",
    }
    
    if reference in verse_database:
        return verse_database[reference]
    
    raise HTTPException(
        status_code=404,
        detail=f"Verse not found. Try: {', '.join(verse_database.keys())}"
    )


def fetch_from_api_bible(reference: str, api_key: str) -> str:
    """
    Fetch from API.Bible (SBLGNT)
    Get free key at: https://scripture.api.bible
    """
    # SBLGNT Bible ID on API.Bible
    bible_id = "de4e12af7f28f599-02"  # Greek SBLGNT
    
    # Convert reference format (e.g., "John 1:1" -> "JHN.1.1")
    book_map = {
        "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN",
        "Acts": "ACT", "Romans": "ROM", "1 Corinthians": "1CO", "2 Corinthians": "2CO",
        "Galatians": "GAL", "Ephesians": "EPH", "Philippians": "PHP", "Colossians": "COL",
        "1 Thessalonians": "1TH", "2 Thessalonians": "2TH", "1 Timothy": "1TI", "2 Timothy": "2TI",
        "Titus": "TIT", "Philemon": "PHM", "Hebrews": "HEB", "James": "JAS",
        "1 Peter": "1PE", "2 Peter": "2PE", "1 John": "1JN", "2 John": "2JN", "3 John": "3JN",
        "Jude": "JUD", "Revelation": "REV"
    }
    
    ref_parts = parse_reference(reference)
    book_code = book_map.get(ref_parts["book"], ref_parts["book"].upper()[:3])
    verse_id = f"{book_code}.{ref_parts['chapter']}.{ref_parts['verse_start']}"
    
    url = f"https://api.scripture.api.bible/v1/bibles/{bible_id}/verses/{verse_id}"
    headers = {"api-key": api_key}
    params = {"content-type": "text"}
    
    response = requests.get(url, headers=headers, params=params, timeout=10)
    response.raise_for_status()
    
    data = response.json()
    greek_text = data['data']['content'].strip()
    
    # Clean HTML tags if present
    import re
    greek_text = re.sub(r'<[^>]+>', '', greek_text)
    
    return greek_text


def fetch_from_bibleapi(reference: str) -> str:
    """
    Fetch from BibleAPI.com (free, no auth needed)
    """
    # This API might work for some verses
    ref_parts = parse_reference(reference)
    book = ref_parts["book"].lower()
    chapter = ref_parts["chapter"]
    verse = ref_parts["verse_start"]
    
    url = f"https://bible-api.com/{book}+{chapter}:{verse}?translation=kjv"
    
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    
    data = response.json()
    
    # Note: This returns English, not Greek
    # This is just a fallback - you'd need to find a Greek-specific free API
    # For now, this will just throw an error to move to next fallback
    
    raise ValueError("BibleAPI.com doesn't provide Greek text")

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
