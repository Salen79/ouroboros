import pytest
from fastapi.testclient import TestClient
from prism_backend.main import app # Assuming main.py is the entry point

client = TestClient(app)

def test_read_root():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# Add more tests for other endpoints and functionalities
