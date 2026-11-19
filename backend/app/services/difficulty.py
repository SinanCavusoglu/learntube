"""Derived difficulty from genuine scheduled ReviewEvent ratings."""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import text
from sqlmodel import Session, select

from app.models import VocabularyItem


def classify(ratings: list[str]) -> dict:
    """Ratings are ordered newest first; at most the latest ten are needed."""
    recent = ratings[:10]
    last_five = recent[:5]
    again_five = last_five.count('again')
    again_ten = recent.count('again')
    difficult = len(recent) >= 2 and (again_five >= 2 or again_ten >= 3)
    # A run of successes can retire an older ten-review trigger once the
    # latest five reviews contain no failure.
    if difficult and len(recent) >= 5 and again_five == 0:
        successes = 0
        for rating in recent:
            if rating not in ('good', 'easy'):
                break
            successes += 1
        if successes >= 3:
            difficult = False
    window = 5 if again_five >= 2 else 10
    count = again_five if window == 5 else again_ten
    reason = f'Again {count} times in your last {min(len(recent), window)} scheduled reviews.' if difficult else None
    return {'automatic_difficult': difficult, 'difficulty_reason': reason,
            'recent_again_count': count if difficult else again_five,
            'review_events_available': len(recent),
            'history_state': 'recorded' if recent else 'unclassified'}


def difficult_words(session: Session) -> list[dict]:
    # One bounded window query avoids loading years of history or querying per word.
    rows = session.execute(text('''
        SELECT vocabulary_id, rating FROM (
            SELECT vocabulary_id, rating,
                   ROW_NUMBER() OVER (PARTITION BY vocabulary_id ORDER BY reviewed_at DESC, id DESC) AS position
            FROM reviewevent
        ) WHERE position <= 10 ORDER BY vocabulary_id, position
    ''')).all()
    ratings: dict[int, list[str]] = defaultdict(list)
    for item_id, rating in rows:
        ratings[item_id].append(rating)
    result = []
    for item in session.exec(select(VocabularyItem).order_by(VocabularyItem.created_at.desc())).all():
        info = classify(ratings[item.id])
        if info['automatic_difficult']:
            result.append({'item': item.model_dump(), **info})
    return result


def difficulty_stats(words: list[dict]) -> dict:
    now = datetime.now(timezone.utc)
    return {'total': len(words),
            'due': sum(word['item']['next_review_at'] is None or
                       word['item']['next_review_at'].replace(tzinfo=timezone.utc) <= now
                       for word in words),
            'practice_available': len(words)}
