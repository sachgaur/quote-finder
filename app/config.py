import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


@dataclass
class Settings:
    youtube_key: str = field(default_factory=lambda: os.getenv('YOUTUBE_API_KEY', ''))
    jev_key: str = field(default_factory=lambda: os.getenv('JEV_API_KEY', ''))
    model: str = field(default_factory=lambda: os.getenv('JEV_MODEL', 'jev-1.13.0'))
    redis_url: str = field(default_factory=lambda: os.getenv('REDIS_URL', ''))
    proxy_url: str = field(default_factory=lambda: os.getenv('TRANSCRIPT_PROXY_URL', ''))
    extension_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        value.strip().rstrip('/') for value in os.getenv('CHROME_EXTENSION_ORIGINS', '').split(',') if value.strip()
    ))
    deployed: bool = field(default_factory=lambda: os.getenv('VERCEL') == '1')
    timeout: float = field(default_factory=lambda: float(os.getenv('ANALYSIS_TIMEOUT_SECONDS', '120')))
    max_characters: int = 180_000
    max_candidates: int = 4000
    concurrency: int = 4
    batch_size: int = 8
    jev_rps: int = field(default_factory=lambda: int(os.getenv('JEV_REQUESTS_PER_SECOND', '10')))
    per_ip_hour: int = 12
    fidelity_threshold: float = field(default_factory=lambda: float(os.getenv('FIDELITY_THRESHOLD', '0.65')))
    # Provisional until a human-labelled held-out set has been evaluated.
    confidence_threshold: float = field(default_factory=lambda: float(os.getenv('CONFIDENCE_THRESHOLD', '0.30')))
    input_price_per_million: float = field(default_factory=lambda: float(os.getenv('JEV_INPUT_PRICE_PER_MILLION', '0.042')))

    def missing(self):
        missing = [name for name, value in [('YOUTUBE_API_KEY', self.youtube_key), ('JEV_API_KEY', self.jev_key)] if not value]
        if self.deployed and not self.redis_url:
            missing.append('REDIS_URL')
        return missing
