from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import json
import os
import re
from functools import lru_cache
from typing import List, Dict, Any

app = FastAPI(title="Greek Lexicon Analyzer API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

class VerseRequest(BaseModel):
    reference: str

# ==================== CONFIG ====================
KIMI_API_KEY = os.getenv("KIMI_API_KEY", "").strip()

if not KIMI_API_KEY:
    raise RuntimeError("KIMI_API_KEY environment variable is required")

# Auto-detect provider
if KIMI_API_KEY.startswith("sk-or-"):
    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL = "openai/gpt-4o-mini"
    PROVIDER = "openrouter"
else:
    API_URL = "https://api.moonshot.cn/v1/chat/completions"
    MODEL = "moonshot-v1-128k"
    PROVIDER = "moonshot"

# ==================== PROMPT ====================
LEXICON_PROMPT = """You are a world-class Koine Greek lexical parser. Your ONLY task is to output a perfectly valid JSON array and NOTHING else.

For every single Greek word in the verse (in exact order, including articles, conjunctions, particles — never skip any word), output:

[{"word":"exact Greek word with diacritics","strong":"G####","lemma":"dictionary form","translation":"most common English","alternatives":["alt1","alt2","alt3",...]}]

STRICT RULES — YOU MUST OBEY:
- One JSON object per Greek word/token
- Strong's number in format G0001 to G5624. If unknown, use G0000
- Provide AT LEAST 15 real alternative English translations per word (draw from LSJ, Donnegan, Thayer, BDAG, Abbott-Smith, etc.)
- Never output punctuation as a separate token
- Never add explanations, markdown, ```json blocks, or any text outside the array
- Output must be 100% valid JSON parsable by json.loads()
- Do not truncate or summarize — full analysis required

Verse to analyze:
<verse>{greek_text}</verse>"""

# ==================== DEMO VERSES ====================
DEMO_VERSES = {
    "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος.",
    "John 3:16": "Οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον, ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν, ἵνα πᾶς ὁ πιστεύων εἰς αὐτὸν μὴ ἀπόληται ἀλλ᾽ ἔχῃ ζωὴν αἰώνιον.",
    "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσιν τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν, τοῖς κατὰ πρόθεσιν κλητοῖς οὖσιν.",
    "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι, ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν.",
    "Philippians 2:5-6": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ, ὃς ἐν μορφῇ θεοῦ ὑπάρχων οὐχ ἁρπαγμὸν ἡγήσατο τὸ εἶναι ἴσα θεῷ,",
}

# ==================== HELPERS ====================
def normalize_reference(ref: str) -> str:
    ref = ref.strip()
    # Handle john1:1, Jn.1.1, john 1:1, etc.
    ref = re.sub(r'\.(\d+)', r' \1', ref)  # Jn.1.1 → Jn. 1.1
    ref = re.sub(r'[\s:]+', ' ', ref)
    parts = ref.split(" ", 1)
    if len(parts) == 2 and parts[1][0].isdigit():
        book = parts[0].title()
        chapter_verse = parts[1].replace(" ", ":")
        ref = f"{book} {chapter_verse}"
    return ref

def extract_json_array(text: str) -> List[Dict[str, Any]]:
    text = text.strip()
    
    # Remove markdown code blocks
    if text.startswith("```"):
        # Extract content between first and last ```
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[2] if parts[1].startswith(("json", "JSON")) else parts[1]
    
    # Find the outermost [...] 
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON array found in response")
    
    json_str = match.group(0)
    
    # Aggressive cleanup of common LLM mistakes
    json_str = re.sub(r",\s*}", "}", json_str)   # trailing comma in object
    json_str = re.sub(r",\s*,", ",", json_str)   # double comma
    json_str = re.sub(r",\s*]", "]", json_str)   # trailing comma in array
    
    try:
        data = json.loads(json_str)
        if not isinstance(data, list):
            raise ValueError("Root is not a JSON array")
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parsing failed: {e}\nRaw extracted:\n{json_str[:1000]}")

@lru_cache(maxsize=256)
def fetch_greek_text_cached(reference: str) -> str:
    reference = normalize_reference(reference)
    
    # Demo verses (always available, with proper punctuation)
    if reference in DEMO_VERSES:
        return DEMO_VERSES[reference]
    
    # Try getbible.net SBLGNT (free, no key)
    try:
        ref_url = reference.replace(" ", "+")
        url = f"https://getbible.net/v2/sblgnt/{ref_url}.json"
        resp = requests.get(url, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        
        verses = data.get("verses", {})
        if not verses:
            raise ValueError("Empty verses")
            
        text_parts = []
        for chapter in verses.values():
            for verse in chapter.values():
                text = verse.get("text", "").strip()
                if text:
                    text_parts.append(text)
        
        full_text = " ".join(text_parts)
        if full_text:
            return full_text
    except Exception as e:
        print(f"getbible.net failed for {reference}: {e}")
    
    raise HTTPException(
        status_code=404,
        detail=f"Verse not found: '{reference}'. Demo verses: {', '.join(DEMO_VERSES.keys())}"
    )

# ==================== ENDPOINT ====================
@app.post("/api/analyze")
async def analyze_verse(request: VerseRequest):
    ref = normalize_reference(request.reference)
    
    try:
        greek_text = fetch_greek_text_cached(ref)
        
        # Build final prompt
        final_prompt = LEXICON_PROMPT.replace("{greek_text}", greek_text)
        
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": final_prompt},
                {"role": "user", "content": "Analyze now."}
            ],
            "temperature": 0.2,
            "max_tokens": 4096,
            "top_p": 0.95
        }
        
        response = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {KIMI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90
        )
        
        response.raise_for_status()
        result = response.json()
        
        content = result["choices"][0]["message"]["content"].strip()
        
        if not content:
            raise ValueError("Empty response from LLM")
        
        analysis = extract_json_array(content)
        
        # Basic validation
        if len(analysis) == 0:
            raise ValueError("Empty analysis array")
            
        return {
            "reference": ref,
            "greek_text": greek_text,
            "word_count": len(analysis),
            "analysis": analysis,
            "model": MODEL,
            "provider": PROVIDER
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Analysis failed: {str(e)}"
        )

# ==================== BASIC ROUTES ====================
@app.get("/")
async def root():
    return {
        "message": "Greek Lexicon Analyzer API v3.0",
        "status": "running",
        "model": MODEL,
        "demo_verses": list(DEMO_VERSES.keys())
    }

@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL}

@app.get("/demo")
async def demo():
    return {"demo_verses": DEMO_VERSES}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app" if __file__ == "main.py" else app, host="0.0.0.0", port=port, reload=False)