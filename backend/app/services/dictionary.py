"""Small, fixed-host client for the free English Dictionary API."""
import json
from urllib.parse import quote

import requests
from fastapi import HTTPException

BASE_URL = 'https://api.dictionaryapi.dev/api/v2/entries/en/'
MAX_BYTES = 512_000


def lookup(word: str) -> dict:
    normalized = ' '.join(word.split())
    if not normalized or len(normalized) > 100 or any(ord(char) < 32 for char in normalized):
        raise HTTPException(422, 'Enter an English word or phrase of up to 100 characters.')
    url = BASE_URL + quote(normalized, safe='')
    try:
        response = requests.get(url, timeout=(3, 8), allow_redirects=False, stream=True)
        with response:
            if response.status_code == 404:
                raise HTTPException(404, 'No dictionary definition found.')
            if response.status_code == 429:
                raise HTTPException(429, 'Dictionary is busy. Try again later.')
            if response.status_code != 200:
                raise HTTPException(503, 'Dictionary is temporarily unavailable.')
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=16_384):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(502, 'Dictionary response is too large.')
                chunks.append(chunk)
            try:
                payload = json.loads(b''.join(chunks))
            except (ValueError, UnicodeError):
                raise HTTPException(502, 'Dictionary returned an invalid response.') from None
    except HTTPException:
        raise
    except requests.RequestException:
        raise HTTPException(503, 'Dictionary could not be reached. Try again later.') from None

    if not isinstance(payload, list):
        raise HTTPException(502, 'Dictionary returned an invalid response.')
    definitions = []
    examples = []
    seen_definitions = set()
    seen_examples = set()
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        meanings = entry.get('meanings')
        for meaning in meanings if isinstance(meanings, list) else []:
            if not isinstance(meaning, dict):
                continue
            part_of_speech = meaning.get('partOfSpeech', '')
            if not isinstance(part_of_speech, str):
                part_of_speech = ''
            items = meaning.get('definitions')
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                definition = item.get('definition')
                if isinstance(definition, str):
                    definition = ' '.join(definition.split())[:2000]
                    if definition and definition.casefold() not in seen_definitions and len(definitions) < 12:
                        definitions.append({'definition': definition, 'part_of_speech': part_of_speech[:40]})
                        seen_definitions.add(definition.casefold())
                example = item.get('example')
                if isinstance(example, str):
                    example = ' '.join(example.split())[:1000]
                    if example and example.casefold() not in seen_examples and len(examples) < 3:
                        examples.append(example)
                        seen_examples.add(example.casefold())
    if not definitions:
        raise HTTPException(404, 'No dictionary definition found.')
    return {'word': normalized, 'definitions': definitions, 'examples': examples}
