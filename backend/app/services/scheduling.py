from datetime import datetime, timedelta, timezone
from app.models import VocabularyItem

def schedule(item: VocabularyItem, rating: str, at: datetime) -> None:
    """Again: 10 minutes, learning. Good: 1 day for new, else max(1, round(interval*ease)).
    Easy: 4 days for new, else max(interval+1, round(interval*ease*1.3)).
    Mastered needs at least 3 successful reviews and an interval >=21 days.
    All timestamps use UTC; due means next_review_at <= current UTC instant.
    """
    if rating not in {'again', 'good', 'easy'}:
        raise ValueError('Invalid review rating')
    previous_count = item.review_count
    item.review_count += 1
    if rating == 'again':
        item.interval_days = 0
        item.ease_factor = max(1.3, item.ease_factor - 0.2)
        item.status = 'learning'
        item.next_review_at = at + timedelta(minutes=10)
    else:
        item.successful_review_count += 1
        if previous_count == 0:
            item.interval_days = 1 if rating == 'good' else 4
        elif rating == 'good':
            item.interval_days = max(1, round(max(1, item.interval_days) * item.ease_factor))
        else:
            item.interval_days = max(item.interval_days + 1, round(max(1, item.interval_days) * item.ease_factor * 1.3))
            item.ease_factor = min(3.0, item.ease_factor + 0.1)
        item.status = 'mastered' if item.interval_days >= 21 and item.successful_review_count >= 3 else 'reviewing'
        item.next_review_at = at + timedelta(days=item.interval_days)
