from datetime import date, datetime, time, timezone
from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import CheckConstraint, UniqueConstraint

def now() -> datetime: return datetime.now(timezone.utc)

class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    youtube_id: str = Field(index=True, unique=True)
    url: str
    title: str = 'Untitled video'
    created_at: datetime = Field(default_factory=now)
    last_watched_at: Optional[datetime] = None
    playback_position: float = 0

class TranscriptSegment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(foreign_key='video.id', index=True)
    text: str
    start: Optional[float] = None
    duration: Optional[float] = None
    is_manual: bool = False

class VideoNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(foreign_key='video.id', index=True, unique=True)
    content: str = ''
    updated_at: datetime = Field(default_factory=now)

class VocabularyItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str
    meaning: str = ''
    example_sentence: str = ''
    personal_note: str = ''
    part_of_speech: str = ''
    cefr_level: str = ''
    collocations: str = ''
    usage_note: str = ''
    synonyms: str = ''
    source_video_id: Optional[int] = Field(default=None, foreign_key='video.id', index=True)
    source_timestamp: Optional[float] = None
    source_pdf_id: Optional[int] = Field(default=None, foreign_key='pdfdocument.id', index=True)
    source_pdf_title: Optional[str] = None
    source_page: Optional[int] = None
    source_note_id: Optional[int] = Field(default=None, foreign_key='notebooknote.id', index=True)
    source_note_title: Optional[str] = None
    source_episode_id: Optional[int] = Field(default=None, foreign_key='podcastepisode.id', index=True)
    source_episode_title: Optional[str] = None
    source_podcast_title: Optional[str] = None
    source_episode_timestamp: Optional[float] = None
    created_at: datetime = Field(default_factory=now)
    status: str = 'new'
    review_count: int = 0
    successful_review_count: int = 0
    interval_days: int = 0
    ease_factor: float = 2.5
    next_review_at: Optional[datetime] = None

class ReviewEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    vocabulary_id: int = Field(foreign_key='vocabularyitem.id', index=True)
    rating: str
    reviewed_at: datetime = Field(default_factory=now, index=True)
    previous_status: str
    next_status: str
    interval_days: int

class WritingSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_type: int
    question: str = ''
    essay_content: str = ''
    notes: str = ''
    chatgpt_feedback: str = ''
    feedback_revision: int = 0
    timer_duration_seconds: int = 1200
    elapsed_seconds: float = 0
    timer_status: str = 'idle'
    timer_started_at: Optional[datetime] = None
    status: str = 'draft'
    word_count: int = 0
    revision: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    completed_at: Optional[datetime] = None


class AIUsage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: str = Field(unique=True, index=True)
    day: str = Field(index=True)
    created_at: datetime = Field(default_factory=now, index=True)

class StudyActivity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_key: str = Field(index=True, unique=True)
    client_session_id: str = Field(index=True)
    activity_type: str = Field(index=True)
    source_id: Optional[int] = None
    started_at: datetime = Field(index=True)
    ended_at: datetime = Field(index=True)
    active_duration_seconds: float
    created_at: datetime = Field(default_factory=now)


class StudyPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: str = Field(unique=True, index=True)
    title: str
    category: str
    description: str = ''
    start_date: date = Field(index=True)
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_untimed: bool = False
    recurrence: str = 'none'
    weekdays: str = ''
    repeat_until: Optional[date] = Field(default=None, index=True)
    timezone: str = 'UTC'
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    status: str = 'planned'  # Used only by one-time plans.
    estimated_pomodoros: int = 1
    focus_minutes: Optional[int] = None
    short_break_minutes: Optional[int] = None
    long_break_minutes: Optional[int] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class StudyPlanOverride(SQLModel, table=True):
    __table_args__ = (UniqueConstraint('plan_id', 'occurrence_date', name='ux_studyplanoverride_occurrence'),)
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key='studyplan.id', index=True)
    occurrence_date: date = Field(index=True)  # Stable original occurrence identity.
    date_override: Optional[date] = Field(default=None, index=True)
    is_modified: bool = False
    title: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    is_untimed: Optional[bool] = None
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    status: str = 'planned'  # planned/completed/skipped/deleted
    estimated_pomodoros: Optional[int] = None
    focus_minutes: Optional[int] = None
    short_break_minutes: Optional[int] = None
    long_break_minutes: Optional[int] = None
    updated_at: datetime = Field(default_factory=now)


class FocusSettings(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    focus_minutes: int = 30
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    long_break_after: int = 4
    auto_start_breaks: bool = False
    auto_start_focus: bool = False
    notification_sound: bool = True
    browser_notifications: bool = False
    ticking_sound: bool = False


class FocusSession(SQLModel, table=True):
    id: str = Field(primary_key=True)
    phase: str
    status: str = Field(index=True)
    target_seconds: int
    verified_seconds: float = 0
    task_plan_id: Optional[int] = Field(default=None, index=True)
    task_occurrence_date: Optional[date] = Field(default=None, index=True)
    task_date: Optional[date] = None
    task_title: str = ''
    category: str = 'General Study'
    started_at: datetime = Field(default_factory=now, index=True)
    updated_at: datetime = Field(default_factory=now)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    revision: int = 0

class PDFDocument(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    original_filename: str
    stored_filename: str = Field(unique=True, index=True)
    file_size_bytes: int
    total_pages: int
    last_page: int = 1
    reading_progress: float = 0
    zoom: float = 1
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    last_opened_at: Optional[datetime] = None

class PDFNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    pdf_id: int = Field(foreign_key='pdfdocument.id', index=True, unique=True)
    content: str = ''
    updated_at: datetime = Field(default_factory=now)


class Bookmark(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint('(video_id IS NOT NULL AND pdf_id IS NULL AND timestamp_seconds IS NOT NULL AND page_number IS NULL) OR (video_id IS NULL AND pdf_id IS NOT NULL AND timestamp_seconds IS NULL AND page_number IS NOT NULL)', name='ck_bookmark_source'),
        CheckConstraint('timestamp_seconds IS NULL OR timestamp_seconds >= 0', name='ck_bookmark_time'),
        CheckConstraint('page_number IS NULL OR page_number >= 1', name='ck_bookmark_page'),
        UniqueConstraint('video_id', 'timestamp_seconds', 'title', name='ux_bookmark_video_position_title'),
        UniqueConstraint('pdf_id', 'page_number', 'title', name='ux_bookmark_pdf_page_title'),
    )
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: Optional[int] = Field(default=None, foreign_key='video.id', index=True)
    pdf_id: Optional[int] = Field(default=None, foreign_key='pdfdocument.id', index=True)
    timestamp_seconds: Optional[float] = None
    page_number: Optional[int] = None
    title: str
    note: str = ''
    created_at: datetime = Field(default_factory=now, index=True)
    updated_at: datetime = Field(default_factory=now)

class Notebook(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ''
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

class NotebookNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    notebook_id: int = Field(foreign_key='notebook.id', index=True)
    title: str = 'Untitled note'
    content: str = ''
    is_pinned: bool = False
    revision: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

class Podcast(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    feed_url: str = Field(unique=True, index=True)
    title: str
    description: str = ''
    image_url: Optional[str] = None
    publisher: str = ''
    external_directory_id: Optional[int] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    created_at: datetime = Field(default_factory=now)
    refreshed_at: datetime = Field(default_factory=now)

class PodcastEpisode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    podcast_id: int = Field(foreign_key='podcast.id', index=True)
    guid: str = Field(index=True)
    title: str
    description: str = ''
    audio_url: Optional[str] = None
    image_url: Optional[str] = None
    published_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    transcript_url: Optional[str] = None
    transcript_type: Optional[str] = None
    created_at: datetime = Field(default_factory=now)

class EpisodeTranscriptSegment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key='podcastepisode.id', index=True)
    text: str
    start: Optional[float] = None
    duration: Optional[float] = None
    is_manual: bool = False

class EpisodeNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key='podcastepisode.id', index=True, unique=True)
    content: str = ''
    updated_at: datetime = Field(default_factory=now)

class EpisodeProgress(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key='podcastepisode.id', index=True, unique=True)
    position_seconds: float = 0
    duration_seconds: Optional[float] = None
    playback_speed: float = 1
    completed: bool = False
    updated_at: datetime = Field(default_factory=now)

class ExternalListening(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    episode_id: int = Field(foreign_key='podcastepisode.id', index=True)
    duration_seconds: Optional[float] = None
    listened_at: datetime = Field(default_factory=now)
