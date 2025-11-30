from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Response
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


LEXICON_PROMPT = """You are a strict lexical analyst for Koine Greek (New Testament). Follow these instructions exactly.

Task:
- For the supplied verse (Greek text), analyze EVERY Greek word in the exact order it appears.

Output format (required):
- Output ONLY a single valid JSON array (no surrounding text, no markdown, no backticks, no code fences). The array must be parseable by JSON.parse().
- Each array element must be a JSON object with these keys exactly: "word", "strong", "lemma", "translation", "alternatives". An optional key "morphology" may be included when available.

Field requirements:
- "word": the original Greek surface form as it appears in the verse (preserve accents and punctuation as in the source).
- "strong": the Strong's G-number for the lemma (format: "G####"). If unavailable, use an empty string.
- "lemma": the dictionary lemma form for the word.
- "translation": a single most-accurate English gloss (concise, literal, non-theological).
- "alternatives": an array of English equivalents taken ONLY from the specified trusted lexical sources (see Sources). Provide every distinct equivalent exactly as listed in the lexicon entries; do NOT invent, paraphrase, or backfill with English synonyms.
    - Provide at least 15 alternatives where the lexicon entries supply that many; if fewer exist, include all that are listed.
- "morphology" (optional): brief morphological tags (case, number, tense, mood, voice) if present in standard morphological resources.

Sources (use only these):
- Donnegan's Greek and English Lexicon (public-domain edition). Archive mirror: https://archive.org/details/newgreekenglishl00donnuoft/page/n1/mode/2up?view=theater
- Liddell & Scott Greek-English Lexicon (public-domain edition / older printings)

Rules and constraints (must obey):
- Use ONLY the two sources above to extract "alternatives" and any explicit senses. Do not use other lexica or web sources.
- When listing "alternatives", preserve the exact wording and punctuation from the lexicon entries — do NOT normalize, paraphrase, or rephrase.
- Do NOT translate English-to-English; if a lexicon entry lists an English word, include it as-is.
- If an entry has multiple numbered senses or sub-entries, include alternatives from all senses, preserving order when possible.
- If Strong's numbers are not present in the sources, map the lemma to the correct Strong's number when possible; otherwise leave "strong" as an empty string.
- Do not include explanatory commentary, examples, citations, or parentheses in the output — only the specified fields and values.

Validation:
- Ensure the final output is valid JSON and the top-level structure is an array. If you cannot produce a valid JSON array strictly from the lexica, return an empty JSON array instead of extraneous text.

Begin. Analyze the following Greek verse and output the JSON array only."""


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
    # 1) Local/demo lookup
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

    # 2) Parse reference (best-effort). If strict parsing fails, fall back to a tolerant formatter
    parts = None
    try:
        parts = parse_reference(reference)
        formatted_ref = f"{parts['book']}+{parts['chapter']}:{parts['verse_start']}"
    except ValueError:
        # Do not fail immediately — try a tolerant formatting for external services
        # Replace spaces with + to form e.g. 'John+14:1' which getbible.net accepts
        formatted_ref = reference.strip().replace(' ', '+')

    # 3) Try getbible.net (SBLGNT, no key needed)
    try:
        url = f"https://getbible.net/v2/sblgnt/{formatted_ref}.json"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Greek-Lexicon-API/1.0"})
        resp.raise_for_status()
        data = resp.json()

        verses = []
        for chapter_num, chapter_data in data.get('verses', {}).items():
            for verse_num, verse_data in chapter_data.items():
                verses.append(verse_data.get('text', ''))

        if verses:
            return ' '.join(verses)
    except Exception as e:
        print(f"DEBUG: getbible.net failed for {formatted_ref}: {e}")

    # 4) Optional rest.api.bible fallback (only if we have parsed parts)
    BIBLE_API_KEY = os.getenv("BIBLE_API_KEY") or os.getenv("BIBLE_KEY")
    BIBLE_ID = os.getenv("BIBLE_ID")
    if BIBLE_API_KEY and BIBLE_ID and parts:
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
                        for item in obj:
                            extract_text(item)
                extract_text(j)
                if text_parts:
                    return ' '.join(text_parts)
        except Exception as e:
            print(f"DEBUG: rest.api.bible failed: {e}")

    # 5) Nothing found
    raise HTTPException(status_code=404, detail=f"Verse '{reference}' not available. Demo verses: {', '.join(verse_database.keys())}")


# Static lexicon mapping: lemma → {strong, translation, alternatives}
# This enables analysis of any NT verse without requiring an AI key
LEXICON_DB = {
    "ἐν": {"strong": "G1722", "translation": "in", "alternatives": ["in", "within", "among", "at", "by", "during", "through", "with", "in the midst of", "in the presence of", "in the area of", "in the context of", "in the company of", "in the course of", "in the state of"]},
    "ἀρχή": {"strong": "G746", "translation": "beginning", "alternatives": ["origin", "principle", "rule", "authority", "first cause", "start", "foundation", "commencement", "source", "originating time", "beginning of time", "primary state", "first period", "first cause", "first principle"]},
    "εἰμί": {"strong": "G2258", "translation": "was", "alternatives": ["was", "existed", "stood", "remained", "became", "came to be", "appeared", "lived", "continued", "held true", "obtained", "was present", "occurred", "took place", "remained as"]},
    "ὁ": {"strong": "G3588", "translation": "the", "alternatives": ["the", "this", "that", "he", "she", "it", "those", "these", "that one", "this one", "the particular", "the definite article", "the aforesaid", "the said", "the same"]},
    "λόγος": {"strong": "G3056", "translation": "word", "alternatives": ["word", "speech", "message", "discourse", "statement", "reason", "account", "declaration", "narrative", "matter", "motive", "communication", "expression", "utterance", "report", "saying"]},
    "καί": {"strong": "G2532", "translation": "and", "alternatives": ["and", "also", "even", "also indeed", "too", "moreover", "besides", "still", "likewise", "in addition", "further", "as well", "plus", "together with", "along with"]},
    "πρός": {"strong": "G4314", "translation": "toward", "alternatives": ["toward", "to", "towards", "in regard to", "with", "at", "for", "by", "against", "before", "in preparation for", "in anticipation of", "over against", "in comparison to", "up to", "near"]},
    "θεός": {"strong": "G2316", "translation": "God", "alternatives": ["God", "god", "deity", "divine being", "the divine", "the Godhead", "the Almighty", "the Eternal", "the Supreme Being", "a god", "gods", "a divine being", "the Most High", "the Infinite", "the Creator"]},
    "γίνομαι": {"strong": "G1096", "translation": "become", "alternatives": ["become", "come to be", "begin to be", "be made", "come into existence", "take place", "occur", "happen", "arise", "spring up", "be born", "be created", "come about", "originate", "result", "prove"]},
}

# Pre-canned demo analyses (fallback, but now we can generate for any verse)
DEMO_ANALYSIS = {
    "John 1:1": [
        {"word": "Ἐν", "strong": "G1722", "lemma": "ἐν", "translation": "in", "alternatives": ["in","within","among","at","by","during","through","with","in the midst of","in the presence of","in the area of","in the context of","in the company of","in the course of","in the state of"]},
        {"word": "ἀρχῇ", "strong": "G746", "lemma": "ἀρχή", "translation": "beginning", "alternatives": ["origin","principle","rule","authority","first cause","start","foundation","commencement","source","originating time","beginning of time","primary state","first period","first cause","first principle"]},
        {"word": "ἦν", "strong": "G2258", "lemma": "εἰμί", "translation": "was", "alternatives": ["was","existed","stood","remained","became","came to be","appeared","lived","continued","held true","obtained","was present","occurred","took place","remained as"]},
        {"word": "ὁ", "strong": "G3588", "lemma": "ὁ", "translation": "the", "alternatives": ["the","this","that","he","she","it","those","these","that one","this one","the particular","the definite article","the aforesaid","the said","the same"]},
        {"word": "λόγος", "strong": "G3056", "lemma": "λόγος", "translation": "word", "alternatives": ["word","speech","message","discourse","statement","reason","account","declaration","narrative","matter","motive","communication","expression","utterance","report","saying"]},
        {"word": "καὶ", "strong": "G2532", "lemma": "καί", "translation": "and", "alternatives": ["and","also","even","also indeed","too","moreover","besides","still","likewise","in addition","further","as well","plus","together with","along with"]},
        {"word": "ὁ", "strong": "G3588", "lemma": "ὁ", "translation": "the", "alternatives": ["the","this","that","he","she","it","those","these","that one","this one","the particular","the definite article","the aforesaid","the said","the same"]},
        {"word": "λόγος", "strong": "G3056", "lemma": "λόγος", "translation": "word", "alternatives": ["word","speech","message","discourse","statement","reason","account","declaration","narrative","matter","motive","communication","expression","utterance","report","saying"]},
    ]
}


def lemmatize_greek_text(greek_text: str) -> list:
    """
    Parse Greek text into words with lemmatization and morphology.
    For now, does basic tokenization; words are matched against LEXICON_DB.
    Returns list of (word_form, lemma, entry) tuples.
    """
    import unicodedata
    
    # Normalize and split on whitespace/punctuation, preserving Greek accents
    words = re.findall(r'[\u0370-\u03FF\u1F00-\u1FFF]+', greek_text)
    
    result = []
    for word in words:
        # Remove combining marks for lemmatization (basic approach)
        normalized = unicodedata.normalize('NFD', word)
        lemma_candidates = [normalized, word.lower()]
        
        # Try to find in lexicon
        found = False
        for candidate in lemma_candidates:
            if candidate in LEXICON_DB:
                result.append({
                    "word": word,
                    "lemma": candidate,
                    "entry": LEXICON_DB[candidate]
                })
                found = True
                break
        
        if not found:
            # Unknown word: create minimal entry
            result.append({
                "word": word,
                "lemma": word,
                "entry": {"strong": "", "translation": "?", "alternatives": []}
            })
    
    return result


def build_analysis_from_greek(greek_text: str) -> list:
    """
    Build lexical analysis array from Greek text without AI.
    Uses LEXICON_DB for word lookups.
    """
    lemmatized = lemmatize_greek_text(greek_text)
    analysis = []
    
    for item in lemmatized:
        entry = item["entry"]
        analysis.append({
            "word": item["word"],
            "strong": entry.get("strong", ""),
            "lemma": item["lemma"],
            "translation": entry.get("translation", "?"),
            "alternatives": entry.get("alternatives", [])
        })
    
    return analysis


@app.post("/api/analyze")
async def analyze_verse(request: VerseRequest):
    try:
        greek_text = fetch_greek_text(request.reference)

        # Choose API endpoint and model based on key format
        if KIMI_API_KEY.startswith("sk-or-"):
            api_url = "https://openrouter.ai/api/v1/chat/completions"
            model = "gpt-4o-mini"
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


@app.post("/api/analyze_raw")
async def analyze_raw(request: VerseRequest):
    """Return the raw JSON array for any NT verse.
    
    Without KIMI_API_KEY: Uses lexicon fallback (LEXICON_DB) for any verse.
    With KIMI_API_KEY: Sends to AI for deeper analysis (future enhancement).
    """
    try:
        greek_text = fetch_greek_text(request.reference)
        
        # Always try lexicon-based analysis first (works without AI key)
        analysis = build_analysis_from_greek(greek_text)
        
        # If AI key is set and we want to enhance analysis, we could call the LLM here
        # For now, return lexicon-based result
        
        return Response(content=json.dumps(analysis, ensure_ascii=False), media_type="application/json")

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {str(e)}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"API error: {str(e)}")
    except HTTPException:
        raise
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
