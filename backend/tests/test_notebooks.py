import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.models import ReviewEvent
from app.routers.notebooks import router as notebook_router
from app.routers.vocabulary import router as vocabulary_router


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        app = FastAPI()
        app.include_router(notebook_router)
        app.include_router(vocabulary_router)
        def session_override():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_session] = session_override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_notebook_notes_search_move_revision_and_delete(self):
        first = self.client.post('/api/notebooks', json={'name': 'Grammar'}).json()
        second = self.client.post('/api/notebooks', json={'name': 'Writing'}).json()
        renamed = self.client.patch(f"/api/notebooks/{first['id']}", json={'name': 'English Grammar', 'description': 'Rules'})
        self.assertEqual(renamed.json()['name'], 'English Grammar')
        created = self.client.post('/api/notebooks/notes', json={'notebook_id': first['id'], 'title': 'Present Perfect', 'content': '# Rule\nUse have + participle.'})
        self.assertEqual(created.status_code, 201)
        note = created.json()
        word = self.client.post('/api/vocabulary', json={'text': 'present perfect', 'meaning': 'A tense.', 'source_note_id': note['id']})
        self.assertEqual(word.status_code, 201, word.text)
        self.assertEqual(word.json()['source_note_title'], 'Present Perfect')
        with Session(self.engine) as session:
            session.add(ReviewEvent(vocabulary_id=word.json()['id'], rating='good', previous_status='new', next_status='learning', interval_days=1))
            session.commit()
        draft = {'expected_revision': 0, 'notebook_id': second['id'], 'title': 'Present Perfect', 'content': '# Rule\nUpdated content', 'is_pinned': True}
        saved = self.client.patch(f"/api/notebooks/notes/{note['id']}", json=draft)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['revision'], 1)
        self.assertEqual(self.client.get(f"/api/notebooks/notes/{note['id']}").json()['content'], draft['content'])
        self.assertEqual(self.client.patch(f"/api/notebooks/notes/{note['id']}", json=draft).status_code, 409)
        results = self.client.get('/api/notebooks/notes/search', params={'q': 'updated', 'pinned': 'true'}).json()
        self.assertEqual([item['id'] for item in results], [note['id']])
        self.assertEqual(self.client.get('/api/notebooks/notes/search', params={'notebook_id': first['id']}).json(), [])
        self.assertEqual(len(self.client.get('/api/notebooks/notes/search', params={'notebook_id': second['id']}).json()), 1)
        self.assertEqual(self.client.delete(f"/api/notebooks/{first['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/notebooks/notes/{note['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/notebooks/{second['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/notebooks/notes/{note['id']}").status_code, 404)
        kept = self.client.get(f"/api/vocabulary/{word.json()['id']}").json()
        self.assertIsNone(kept['source_note_id'])
        self.assertEqual(kept['source_note_title'], 'Present Perfect')
        self.assertEqual(len(self.client.get(f"/api/vocabulary/{word.json()['id']}/reviews").json()), 1)

    def test_vocabulary_still_creates_and_lists(self):
        created = self.client.post('/api/vocabulary', json={'text': 'fluent', 'meaning': 'able to speak easily'})
        self.assertEqual(created.status_code, 201)
        phrase = self.client.post('/api/vocabulary', json={'text': 'play a crucial role', 'meaning': '', 'example_sentence': ''})
        self.assertEqual(phrase.status_code, 201)
        items = self.client.get('/api/vocabulary').json()
        self.assertEqual({item['text'] for item in items}, {'fluent', 'play a crucial role'})
