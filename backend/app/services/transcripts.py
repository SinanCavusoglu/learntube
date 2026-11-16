from youtube_transcript_api import YouTubeTranscriptApi

def fetch_english(video_id: str) -> list[dict]:
    tracks = list(YouTubeTranscriptApi().list(video_id))
    english = [track for track in tracks if track.language_code.lower() == 'en' or track.language_code.lower().startswith('en-')]
    if not english:
        raise ValueError('No English captions are available for this video.')
    # Prefer creator captions, then exact English, then regional English variants.
    selected = min(english, key=lambda track: (track.is_generated, track.language_code.lower() != 'en', track.language_code.lower()))
    return [{'text': item.text, 'start': item.start, 'duration': item.duration} for item in selected.fetch()]
