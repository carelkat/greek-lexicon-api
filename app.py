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

Output ONLY valid JSON array:
[{"word":"Greek","strong":"G####","lemma":"lemma","translation":"primary","alternatives":["alt1","alt2",...]}]

Requirements:
- Analyze EVERY word in sequence
- Provide Strong's number for each word
- List at least 15 English alternatives from Liddell & Scott and Donnegan's lexicons
- Output ONLY the JSON array, nothing else"""


def fetch_greek_text(reference: str) -> str:
    """Fetch Greek text from multiple sources with proper fallbacks"""
    
    # Demo verses (instant response)
    demo_verses = {
        "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς τὸν θεόν καὶ θεὸς ἦν ὁ λόγος",
        "John 3:16": "οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν",
        "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσιν τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν",
        "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν",
        "Philippians 2:5": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ",
    }
    
    # Check demo first
    if reference.strip() in demo_verses:
        return demo_verses[reference.strip()]
    
    # Method 1: Try Crosswire/SWORD API (works without auth)
    try:
        # Format: Book Chapter:Verse (e.g., "John 14:1")
        ref_encoded = reference.replace(' ', '%20')
        url = f"https://getbible.net/json?passage={ref_encoded}&version=greek"
        
        response = requests.get(
            url, 
            timeout=15,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        
        if response.status_code == 200:
            # GetBible returns JSONP, strip the callback
            text = response.text
            if text.startswith('(') and text.endswith(')'):
                text = text[1:-1]
            
            data = json.loads(text)
            
            # Extract verse text
            if isinstance(data, dict):
                for book_data in data.values():
                    if isinstance(book_data, dict) and 'chapter' in book_data:
                        for chapter in book_data['chapter'].values():
                            for verse in chapter.values():
                                if 'verse' in verse:
                                    return verse['verse']
    except Exception as e:
        print(f"GetBible failed: {e}")
    
    # Method 2: Try API.Bible if key is available
    api_bible_key = os.getenv("API_BIBLE_KEY")
    if api_bible_key:
        try:
            # SBLGNT Bible ID
            bible_id = "de4e12af7f28f599-02"
            
            # Book code mapping
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
            
            # Parse reference (e.g., "John 14:1" -> JHN.14.1)
            match = re.match(r'(\d?\s*[A-Za-z]+)\s+(\d+):(\d+)', reference)
            if match:
                book_name = match.group(1).strip()
                chapter = match.group(2)
                verse = match.group(3)
                
                book_code = book_codes.get(book_name, book_name[:3].upper())
                verse_id = f"{book_code}.{chapter}.{verse}"
                
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
                    greek_text = re.sub(r'<[^>]+>', '', greek_text).strip()
                    if greek_text:
                        return greek_text
        except Exception as e:
            print(f"API.Bible failed: {e}")
    
    # Method 3: Fallback message
    raise HTTPException(
        status_code=404,
        detail=f"Could not fetch verse '{reference}'. Please check the format (e.g., 'John 14:1') or try one of the demo verses: {', '.join(demo_verses.keys())}"
    )

@app.get("/")
async def root():
    return {"status": "Greek Lexicon API v2.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
