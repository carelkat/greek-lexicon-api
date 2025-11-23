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
        try:
            ref_parts = parse_reference(reference)
            formatted_ref = f"{ref_parts['book']}+{ref_parts['chapter']}:{ref_parts['verse_start']}"

            url = f"https://getbible.net/v2/sblgnt/{formatted_ref}.json"

            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()

            verses = []
            for chapter_num, chapter_data in data.get('verses', {}).items():
                for verse_num, verse_data in chapter_data.items():
                    verses.append(verse_data['text'])

            if not verses:
                raise ValueError("No verse text found")

            return ' '.join(verses)

        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"Could not fetch verse: {str(e)}"
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
                content = content.split('```')[1]
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


    if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
