from fastapi.testclient import TestClient

from backend.app import app


def test_health_and_public_endpoints():
    with TestClient(app) as client:
        health = client.get('/health')
        assert health.status_code == 200
        assert health.json()['status'] == 'ok'
        agents = client.get('/api/agents')
        assert agents.status_code == 200
        assert len(agents.json()['agents']) >= 2
        security = client.post('/api/code/security', json={'code': 'import os'})
        assert security.status_code == 200
        assert security.json()['security']['allowed'] is False


def test_private_routes_require_authentication():
    with TestClient(app) as client:
        response = client.get('/api/memory')
        assert response.status_code == 401
        response = client.post('/api/command/sign', json={'capability': 'workspace.write', 'args': {}, 'confirmed': True})
        assert response.status_code == 401
