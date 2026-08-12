import os

os.environ["DATABASE_URL"] = "sqlite:///./agentseo_test.db"
os.environ["DEMO_MODE"] = "true"

import pytest
from agentseo.database import Base, engine
from agentseo.main import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
