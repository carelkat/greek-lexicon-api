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
    """Fetch Greek text from API.Bible - works for ANY NT verse"""
    
    # Demo verses for offline/testing
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
    
    # Use API.Bible for ANY other verse
    api_key = os.getenv("API_BIBLE_KEY")
    
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="API_BIBLE_KEY not configured. Cannot fetch verses outside demo list."
        )
    
    # Greek Bible ID on API.Bible (SBLGNT)
    bible_id = "de4e12af7f28f599-02"
    
    # Book code mapping
    book_map = {
        "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU",
        "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT", "1 Samuel": "1SA", "2 Samuel": "2SA",
        "1 Kings": "1KI", "2 Kings": "2KI", "1 Chronicles": "1CH", "2 Chronicles": "2CH",
        "Ezra": "EZR", "Nehemiah": "NEH", "Esther": "EST", "Job": "JOB", "Psalms": "PSA",
        "Proverbs": "PRO", "Ecclesiastes": "ECC", "Song of Solomon": "SNG", "Isaiah": "ISA",
        "Jeremiah": "JER", "Lamentations": "LAM", "Ezekiel": "EZK", "Daniel": "DAN",
        "Hosea": "HOS", "Joel": "JOL", "Amos": "AMO", "Obadiah": "OBA", "Jonah": "JON",
        "Micah": "MIC", "Nahum": "NAM", "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG",
        "Zechariah": "ZEC", "Malachi": "MAL",
        "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
        "Romans": "ROM", "1 Corinthians": "1CO", "2 Corinthians": "2CO", "Galatians": "GAL",
        "Ephesians": "EPH", "Philippians": "PHP", "Colossians": "COL", "1 Thessalonians": "1TH",
        "2 Thessalonians": "2TH", "1 Timothy": "1TI", "2 Timothy": "2TI", "Titus": "TIT",
        "Philemon": "PHM", "Hebrews": "HEB", "James": "JAS", "1 Peter": "1PE", "2 Peter": "2PE",
        "1 John": "1JN", "2 John": "2JN", "3 John": "3JN", "Jude": "JUD", "Revelation": "REV"
    }
    
    try:
        # Parse reference: "John 14:1" -> ["John", "14", "1"]
        match = re.match(r'^(\d?\s*[A-Za-z\s]+?)\s+(\d+):(\d+)$', reference.strip())
        
        if not match:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reference format: '{reference}'. Use: Book Chapter:Verse (e.g., John 14:1)"
            )
        
        book_name = match.group(1).strip()
        chapter = match.group(2)
        verse = match.group(3)
        
        # Get book code
        book_code = book_map.get(book_name)
        if not book_code:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown book: '{book_name}'. Check spelling."
            )
        
        # Build verse ID: "JHN.14.1"
        verse_id = f"{book_code}.{chapter}.{verse}"
        
        # Call API.Bible
        url = f"https://api.scripture.api.bible/v1/bibles/{bible_id}/verses/{verse_id}"
        
        response = requests.get(
            url,
            headers={"api-key": api_key},
            params={"content-type": "text", "include-notes": "false", "include-titles": "false"},
            timeout=15
        )
        
        if response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"Verse not found: {reference}. Check book name, chapter, and verse number."
            )
        
        response.raise_for_status()
        
        data = response.json()
        greek_text = data['data']['content']
        
        # Remove HTML tags
        greek_text = re.sub(r'<[^>]+>', '', greek_text).strip()
        
        if not greek_text:
            raise HTTPException(
                status_code=404,
                detail=f"No text found for: {reference}"
            )
        
        return greek_text
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching verse: {str(e)}"
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
