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
    """Simple verse lookup with fallback"""
    
    # Demo verses (always available)
    verses = {
        "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς τὸν θεόν καὶ θεὸς ἦν ὁ λόγος",
        "John 3:16": "οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν",
        "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσιν τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν",
        "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν",
        "Philippians 2:5": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ",
    }
    
    # Check demo verses first
    if reference in verses:
        return verses[reference]
    
    # Try GetBible.net (free, no auth)
    try:
        ref = reference.replace(' ', '+')
        url = f"https://getbible.net/v2/sblgnt/{ref}.json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        text_parts = []
        for chapter in data.get('verses', {}).values():
            for verse in chapter.values():
                text_parts.append(verse.get('text', ''))
        
        if text_parts:
            return ' '.join(text_parts)
    except:
        pass
    
    # Not found
    raise HTTPException(
        status_code=404,
        detail=f"Verse not found. Try: {', '.join(verses.keys())}"
    )


@app.post("/api/analyze")
async def analyze_verse(request: VerseRequest):
    try:
        # Get Greek text
        greek_text = fetch_greek_text(request.reference)
        
        # Choose API based on key
        if KIMI_API_KEY.startswith("sk-or-"):
            api_url = "https://openrouter.ai/api/v1/chat/completions"
            model = "gpt-4o-mini"
        else:
            api_url = "https://api.moonshot.cn/v1/chat/completions"
            model = "moonshot-v1-128k"
        
        # Call AI
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
        content = result['choices'][0]['message']['content'].strip()
        
        # Clean markdown
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
        content = content.strip()
        
        # Parse and return
        lexicon_data = json.loads(content)
        
        return {
            "text": greek_text,
            "reference": request.reference,
            "analysis": lexicon_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
