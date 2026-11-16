from typing import Optional
from pydantic import BaseModel, Field

class VideoCreate(BaseModel): url: str
class ProgressUpdate(BaseModel): position: float = Field(ge=0)
class NoteUpdate(BaseModel): content: str = Field(max_length=100_000)
class ManualTranscript(BaseModel): text: str = Field(min_length=1, max_length=200_000)
class VocabularyCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    meaning: str = ''
    example_sentence: str = ''
    personal_note: str = ''
    part_of_speech: str = Field(default='', max_length=80)
    cefr_level: str = Field(default='', max_length=10)
    collocations: str = Field(default='', max_length=2000)
    usage_note: str = Field(default='', max_length=2000)
    synonyms: str = Field(default='', max_length=1000)
    source_video_id: Optional[int] = None
    source_timestamp: Optional[float] = Field(default=None, ge=0)
    source_pdf_id: Optional[int] = None
    source_page: Optional[int] = Field(default=None, ge=1)
    source_note_id: Optional[int] = None
    source_episode_id: Optional[int] = None
    source_episode_timestamp: Optional[float] = Field(default=None, ge=0)

class VocabularyUpdate(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    meaning: Optional[str] = None
    example_sentence: Optional[str] = None
    personal_note: Optional[str] = None
    part_of_speech: Optional[str] = Field(default=None, max_length=80)
    cefr_level: Optional[str] = Field(default=None, max_length=10)
    collocations: Optional[str] = Field(default=None, max_length=2000)
    usage_note: Optional[str] = Field(default=None, max_length=2000)
    synonyms: Optional[str] = Field(default=None, max_length=1000)

class ReviewCreate(BaseModel):
    rating: str
    expected_review_count: int = Field(ge=0)
