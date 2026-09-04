# ABOUTME: Pytest suite for the Flask todolist app covering auth, CRUD,
# ABOUTME: duplicate handling, the health check and the cleanup token endpoint.
import os

os.environ.setdefault('DATABASE_URI', 'sqlite:///:memory:')
os.environ.setdefault('ADMIN_USER', 'admin')
os.environ.setdefault('ADMIN_PASSWORD', 'admin')
os.environ.setdefault('CLEANUP_TOKEN', 'test-token')

import pytest

import app as todo_app


@pytest.fixture
def client():
    todo_app.app.config['TESTING'] = True
    with todo_app.app.app_context():
        todo_app.db.drop_all()
        todo_app.db.create_all()
    with todo_app.app.test_client() as client:
        yield client


def login(client):
    return client.post('/login', data={'username': 'admin', 'password': 'admin'})


def test_index_requires_login(client):
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_login_with_valid_credentials(client):
    resp = login(client)
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/')


def test_login_with_invalid_credentials(client):
    resp = client.post('/login', data={'username': 'admin', 'password': 'wrong'})
    assert resp.status_code == 200
    assert b'Invalid username or password.' in resp.data


def test_add_task(client):
    login(client)
    client.post('/add', data={'task': 'buy milk'})
    resp = client.get('/')
    assert b'buy milk' in resp.data


def test_add_rejects_duplicate_pending_task(client):
    login(client)
    client.post('/add', data={'task': 'buy milk'})
    resp = client.post('/add', data={'task': 'Buy Milk'}, follow_redirects=True)
    assert b'This task already exists.' in resp.data
    with todo_app.app.app_context():
        assert todo_app.Todo.query.count() == 1


def test_toggle_task(client):
    login(client)
    client.post('/add', data={'task': 'write tests'})
    with todo_app.app.app_context():
        todo = todo_app.Todo.query.first()
        assert todo.done is False
        todo_id = todo.id
    client.post(f'/toggle/{todo_id}')
    with todo_app.app.app_context():
        assert todo_app.Todo.query.get(todo_id).done is True


def test_delete_task(client):
    login(client)
    client.post('/add', data={'task': 'delete me'})
    with todo_app.app.app_context():
        todo_id = todo_app.Todo.query.first().id
    client.post(f'/delete/{todo_id}')
    with todo_app.app.app_context():
        assert todo_app.Todo.query.get(todo_id) is None


def test_healthz(client):
    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert resp.data == b'ok'


def test_cleanup_requires_valid_token(client):
    resp = client.post('/cleanup', headers={'X-Cleanup-Token': 'wrong'})
    assert resp.status_code == 401


def test_cleanup_deletes_done_tasks(client):
    login(client)
    client.post('/add', data={'task': 'done task'})
    with todo_app.app.app_context():
        todo_id = todo_app.Todo.query.first().id
    client.post(f'/toggle/{todo_id}')
    resp = client.post('/cleanup', headers={'X-Cleanup-Token': 'test-token'})
    assert resp.status_code == 200
    assert resp.data == b'deleted 1'
    with todo_app.app.app_context():
        assert todo_app.Todo.query.count() == 0


def test_parse_image_tags_extracts_short_tag():
    assert todo_app._parse_image_tags('') == []
    assert todo_app._parse_image_tags('  ') == []
    assert todo_app._parse_image_tags('user/app:latest') == ['latest']
    assert todo_app._parse_image_tags('user/app:PR-2, user/app:593e277') == [
        'PR-2', '593e277']
    assert todo_app._parse_image_tags('user/app:latest\nuser/app:593e277') == [
        'latest', '593e277']


def test_footer_hidden_without_image_tags(client, monkeypatch):
    monkeypatch.setattr(todo_app, 'IMAGE_TAGS', [])
    login(client)
    resp = client.get('/')
    assert b'version:' not in resp.data


def test_footer_shows_image_tags(client, monkeypatch):
    monkeypatch.setattr(todo_app, 'IMAGE_TAGS', ['PR-2', '593e277'])
    login(client)
    resp = client.get('/')
    assert b'version:' in resp.data
    assert b'PR-2' in resp.data
    assert b'593e277' in resp.data
