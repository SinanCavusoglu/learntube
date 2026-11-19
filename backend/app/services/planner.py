"""Calendar occurrences use local date/time fields; no UTC conversion changes wall time."""

from datetime import date, timedelta

from sqlalchemy import and_, or_
from sqlmodel import Session, select

from app.models import NotebookNote, PDFDocument, StudyPlan, StudyPlanOverride, Video

FALLBACK = {
    'Vocabulary': '/vocabulary', 'Flashcards': '/vocabulary/review',
    'Listening': '/videos', 'Reading': '/pdfs', 'Writing': '/writing',
    'Grammar': '/notebook', 'General Study': '/',
}
DESTINATIONS = {
    'vocabulary': '/vocabulary', 'flashcards': '/vocabulary/review',
    'difficult': '/vocabulary/difficult/practice', 'videos': '/videos',
    'pdfs': '/pdfs', 'writing': '/writing', 'notebook': '/notebook',
}
RESOURCE_MODELS = {'video': Video, 'pdf': PDFDocument, 'note': NotebookNote}


def occurs_on(plan: StudyPlan, day: date) -> bool:
    if day < plan.start_date or (plan.repeat_until and day > plan.repeat_until):
        return False
    if plan.recurrence == 'none':
        return day == plan.start_date
    if plan.recurrence == 'daily':
        return True
    if plan.recurrence == 'weekly':
        return day.weekday() == plan.start_date.weekday()
    return day.weekday() in {int(value) for value in plan.weekdays.split(',') if value}


def _destination(session: Session, category: str, resource_type: str | None, resource_id: int | None) -> tuple[str, bool]:
    fallback = FALLBACK[category]
    if resource_type in RESOURCE_MODELS:
        model = RESOURCE_MODELS[resource_type]
        if resource_id and session.get(model, resource_id):
            if resource_type == 'note':
                return f'/notebook/all/{resource_id}', False
            return f'/{"videos" if resource_type == "video" else "pdfs"}/{resource_id}', False
        return fallback, True
    return DESTINATIONS.get(resource_type, fallback), False


def _display(session: Session, plan: StudyPlan, original: date, override: StudyPlanOverride | None) -> dict:
    edited = override is not None and override.is_modified
    day = override.date_override if edited and override.date_override else original
    fields = {name: getattr(override, name) if edited else getattr(plan, name)
              for name in ('title', 'category', 'description', 'start_time', 'end_time', 'is_untimed', 'resource_type', 'resource_id')}
    url, missing = _destination(session, fields['category'], fields['resource_type'], fields['resource_id'])
    return {'plan_id': plan.id, 'occurrence_date': original, 'date': day,
            'recurring': plan.recurrence != 'none', 'recurrence': plan.recurrence,
            'timezone': plan.timezone, 'status': override.status if override else plan.status,
            'destination_url': url, 'resource_missing': missing, **fields}


def occurrences(session: Session, start: date, end: date) -> list[dict]:
    # Include series whose moved occurrence lands in the requested range.
    moved = session.exec(select(StudyPlanOverride.plan_id).where(StudyPlanOverride.date_override >= start,
                                                                 StudyPlanOverride.date_override <= end)).all()
    query = select(StudyPlan).where(or_(
        and_(StudyPlan.start_date >= start, StudyPlan.start_date <= end),
        and_(StudyPlan.recurrence != 'none', StudyPlan.start_date <= end,
             or_(StudyPlan.repeat_until == None, StudyPlan.repeat_until >= start)),
        StudyPlan.id.in_(moved) if moved else False,
    ))
    plans = session.exec(query).all()
    if not plans:
        return []
    ids = [plan.id for plan in plans]
    overrides = session.exec(select(StudyPlanOverride).where(StudyPlanOverride.plan_id.in_(ids), or_(
        (StudyPlanOverride.occurrence_date >= start) & (StudyPlanOverride.occurrence_date <= end),
        (StudyPlanOverride.date_override >= start) & (StudyPlanOverride.date_override <= end),
    ))).all()
    override_map = {(row.plan_id, row.occurrence_date): row for row in overrides}
    result: list[dict] = []
    seen = set()
    for plan in plans:
        day = max(start, plan.start_date)
        while day <= end:
            if occurs_on(plan, day):
                seen.add((plan.id, day))
                override = override_map.get((plan.id, day))
                if not override or override.status != 'deleted':
                    row = _display(session, plan, day, override)
                    if start <= row['date'] <= end:
                        result.append(row)
            day += timedelta(days=1)
        for (plan_id, original), override in override_map.items():
            if plan_id == plan.id and (plan_id, original) not in seen and occurs_on(plan, original) and override.status != 'deleted':
                row = _display(session, plan, original, override)
                if start <= row['date'] <= end:
                    result.append(row)
    return sorted(result, key=lambda row: (row['date'], row['start_time'] is None, row['start_time'] or '', row['plan_id'], row['occurrence_date']))


def summary(rows: list[dict]) -> dict:
    planned = completed = task_total = task_done = 0
    for row in rows:
        if row['is_untimed']:
            task_total += 1
            task_done += row['status'] == 'completed'
        else:
            minutes = (row['end_time'].hour * 60 + row['end_time'].minute) - (row['start_time'].hour * 60 + row['start_time'].minute)
            planned += minutes  # Skipped blocks remain in original planned total.
            if row['status'] == 'completed':
                completed += minutes
    return {'planned_minutes': planned, 'completed_minutes': completed,
            'completed_tasks': task_done, 'total_tasks': task_total}
