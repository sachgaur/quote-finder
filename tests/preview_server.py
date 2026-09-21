"""Browser-test server ONLY: .venv/bin/uvicorn tests.preview_server:app --port 8001.

Uses synthetic captions and scores; no production configuration or API calls.
"""
from app.config import Settings
from main import create_app
from tests.fixtures import FixtureProviders

app = create_app(Settings(youtube_key='fixture', jev_key='fixture', redis_url='', deployed=False), providers=FixtureProviders(delay=1))
