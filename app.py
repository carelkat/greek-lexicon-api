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
    """Fetch Greek text from multiple Bible APIs with fallbacks"""
    
    # Demo verses (instant, always work)
    demo_verses = {
        "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς τὸν θεόν καὶ θεὸς ἦν ὁ λόγος",
        "John 3:16": "οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν",
        "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσιν τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν",
        "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν",
        "Philippians 2:5": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ",
    }
    
    if reference.strip() in demo_verses:
        return demo_verses[reference.strip()]
    
    errors = []
    
    # METHOD 1: Try bolls.life (Greek SBLGNT, no auth needed)
    try:
        # Format: John+1:1
        ref = reference.replace(' ', '+')
        url = f"https://bolls.life/get-paralel-SBLGNT/{ref}/"
        
        resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                # Extract Greek text from response
                greek_words = [item.get('text', '') for item in data if 'text' in item]
                if greek_words:
                    return ' '.join(greek_words)
    except Exception as e:
        errors.append(f"bolls.life: {str(e)}")
    
    # METHOD 2: Try API.Bible (if key available)
    api_key = os.getenv("API_BIBLE_KEY")
    if api_key:
        try:
            bible_id = "de4e12af7f28f599-02"  # SBLGNT
            
            # Parse reference
            match = re.match(r'^(\d?\s*[A-Za-z\s]+?)\s+(\d+):(\d+)$', reference.strip())
            if match:
                book_map = {
                    "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN",
                    "Acts": "ACT", "Romans": "ROM", "1 Corinthians": "1CO", 
                    "2 Corinthians": "2CO", "Galatians": "GAL", "Ephesians": "EPH",
                    "Philippians": "PHP", "Colossians": "COL", "1 Thessalonians": "1TH",
                    "2 Thessalonians": "2TH", "1 Timothy": "1TI", "2 Timothy": "2TI",
                    "Titus": "TIT", "Philemon": "PHM", "Hebrews": "HEB", "James": "JAS",
                    "1 Peter": "1PE", "2 Peter": "2PE", "1 John": "1JN", "2 John": "2JN",
                    "3 John": "3JN", "Jude": "JUD", "Revelation": "REV"
                }
                
                book = match.group(1).strip()
                chapter = match.group(2)
                verse = match.group(3)
                
                book_code = book_map.get(book)
                if book_code:
                    verse_id = f"{book_code}.{chapter}.{verse}"
                    url = f"https://api.scripture.api.bible/v1/bibles/{bible_id}/verses/{verse_id}"
                    
                    resp = requests.get(
                        url,
                        headers={"api-key": api_key},
                        params={"content-type": "text"},
                        timeout=10
                    )
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        text = data.get('data', {}).get('content', '')
                        text = re.sub(r'<[^>]+>', '', text).strip()
                        if text:
                            return text
        except Exception as e:
            errors.append(f"API.Bible: {str(e)}")
    
    # METHOD 3: Try Crosswire/eBible (another free option)
    try:
        # This might work for some verses
        ref = reference.replace(' ', '%20')
        url = f"https://ebible.org/cgi-bin/getversesext.cgi?version=grcont&txt={ref}"
        
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200 and resp.text.strip():
            # Clean HTML if present
            text = re.sub(r'<[^>]+>', '', resp.text).strip()
            if text and len(text) > 10:
                return text
    except Exception as e:
        errors.append(f"eBible: {str(e)}")
    
    # All methods failed
    raise HTTPException(
        status_code=404,
        detail=f"Could not fetch '{reference}'. Tried multiple sources. Errors: {'; '.join(errors)}. Demo verses available: {', '.join(demo_verses.keys())}"
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
