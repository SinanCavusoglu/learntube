from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import inspect, text
from app import models  # noqa: F401 - register tables before create_all
from app.core.config import DATABASE_URL
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
def migrate_focus_columns(target_engine) -> None:
    additions = {
        'studyplan': {
            'estimated_pomodoros': 'INTEGER NOT NULL DEFAULT 1',
            'focus_minutes': 'INTEGER', 'short_break_minutes': 'INTEGER', 'long_break_minutes': 'INTEGER',
        },
        'studyplanoverride': {
            'estimated_pomodoros': 'INTEGER',
            'focus_minutes': 'INTEGER', 'short_break_minutes': 'INTEGER', 'long_break_minutes': 'INTEGER',
        },
        'focussession': {'task_date': 'DATE'},
    }
    for table, fields in additions.items():
        if not inspect(target_engine).has_table(table):
            continue
        existing = {column['name'] for column in inspect(target_engine).get_columns(table)}
        with target_engine.begin() as connection:
            for name, definition in fields.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))


def create_db_and_tables() -> None:
    # SQLite create_all does not add columns to an existing table. Additive migration preserves rows.
    models.PDFDocument.__table__.create(engine, checkfirst=True)
    models.PDFNote.__table__.create(engine, checkfirst=True)
    models.Notebook.__table__.create(engine, checkfirst=True)
    models.NotebookNote.__table__.create(engine, checkfirst=True)
    models.Podcast.__table__.create(engine, checkfirst=True)
    models.PodcastEpisode.__table__.create(engine, checkfirst=True)
    models.EpisodeTranscriptSegment.__table__.create(engine, checkfirst=True)
    models.EpisodeNote.__table__.create(engine, checkfirst=True)
    models.EpisodeProgress.__table__.create(engine, checkfirst=True)
    models.ExternalListening.__table__.create(engine, checkfirst=True)
    if inspect(engine).has_table('podcast'):
        podcast_columns = {column['name'] for column in inspect(engine).get_columns('podcast')}
        with engine.begin() as connection:
            for name, definition in {'publisher': "VARCHAR NOT NULL DEFAULT ''", 'external_directory_id': 'INTEGER',
                                     'etag': 'VARCHAR', 'last_modified': 'VARCHAR'}.items():
                if name not in podcast_columns:
                    connection.execute(text(f'ALTER TABLE podcast ADD COLUMN {name} {definition}'))
    if inspect(engine).has_table('vocabularyitem'):
        columns = {column['name'] for column in inspect(engine).get_columns('vocabularyitem')}
        additions = {
            'status': "VARCHAR NOT NULL DEFAULT 'new'",
            'review_count': 'INTEGER NOT NULL DEFAULT 0',
            'successful_review_count': 'INTEGER NOT NULL DEFAULT 0',
            'interval_days': 'INTEGER NOT NULL DEFAULT 0',
            'ease_factor': 'FLOAT NOT NULL DEFAULT 2.5',
            'next_review_at': 'DATETIME',
            'source_pdf_id': 'INTEGER REFERENCES pdfdocument(id)',
            'source_pdf_title': 'VARCHAR',
            'source_page': 'INTEGER',
            'source_note_id': 'INTEGER REFERENCES notebooknote(id)',
            'source_note_title': 'VARCHAR',
            'source_episode_id': 'INTEGER REFERENCES podcastepisode(id)',
            'source_episode_title': 'VARCHAR',
            'source_podcast_title': 'VARCHAR',
            'source_episode_timestamp': 'FLOAT',
            'part_of_speech': "VARCHAR NOT NULL DEFAULT ''",
            'cefr_level': "VARCHAR NOT NULL DEFAULT ''",
            'collocations': "VARCHAR NOT NULL DEFAULT ''",
            'usage_note': "VARCHAR NOT NULL DEFAULT ''",
            'synonyms': "VARCHAR NOT NULL DEFAULT ''",
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(text(f'ALTER TABLE vocabularyitem ADD COLUMN {name} {definition}'))
    if inspect(engine).has_table('writingsession'):
        writing_columns = {column['name'] for column in inspect(engine).get_columns('writingsession')}
        with engine.begin() as connection:
            if 'chatgpt_feedback' not in writing_columns:
                connection.execute(text("ALTER TABLE writingsession ADD COLUMN chatgpt_feedback VARCHAR NOT NULL DEFAULT ''"))
            if 'feedback_revision' not in writing_columns:
                connection.execute(text("ALTER TABLE writingsession ADD COLUMN feedback_revision INTEGER NOT NULL DEFAULT 0"))
    migrate_focus_columns(engine)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_focus_active ON focussession((1)) WHERE status IN ('running','paused')"))
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_reviewevent_reviewed_at ON reviewevent (reviewed_at)'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_reviewevent_vocab_recent ON reviewevent (vocabulary_id, reviewed_at DESC, id DESC)'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_vocabularyitem_source_pdf_id ON vocabularyitem (source_pdf_id)'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_vocabularyitem_source_note_id ON vocabularyitem (source_note_id)'))
        connection.execute(text('CREATE INDEX IF NOT EXISTS ix_vocabularyitem_source_episode_id ON vocabularyitem (source_episode_id)'))
        connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_podcastepisode_podcast_guid ON podcastepisode (podcast_id, guid)'))
def get_session():
    with Session(engine) as session: yield session
