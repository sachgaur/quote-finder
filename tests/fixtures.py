"""Synthetic test data, never used by the production application."""
import asyncio

from app.errors import AppError

SENTENCES = [
    'A useful question changes what you notice, not just what you know.',
    'Make the smallest version that can teach you something real.',
    'Clarity is the work of deciding what matters and letting the rest go.',
    'Good feedback describes the distance between an intention and its effect.',
    'The best tools give your attention back to the thing you care about.',
    'Progress becomes visible when you compare your work with yesterday, not with everyone else.',
    'Leave enough room in your plans for something worth discovering.',
    'Listening carefully is often the first useful thing you can do.',
]


class FixtureProviders:
    def __init__(self, delay=0, failure=None, fidelity=.98):
        self.delay, self.failure, self.fidelity = delay, failure, fidelity
        self.scoring_calls = 0
        self.cancelled = False

    async def metadata(self, vid):
        await asyncio.sleep(self.delay)
        return {'id': vid, 'title': 'Designing with intention — synthetic test transcript', 'channel': 'Interface test fixture', 'duration': 624}

    async def transcript(self, vid):
        await asyncio.sleep(self.delay)
        if self.failure:
            raise AppError(self.failure, True)
        return {'snippets': [{'text': text, 'start': 12 + i * 35, 'duration': 12} for i, text in enumerate(SENTENCES)], 'language': 'en', 'is_generated': False}

    async def score_batch(self, client, candidates):
        self.scoring_calls += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return [{'candidate': c, 'score': 9.3 - c.start_seconds / 300, 'fidelity': self.fidelity, 'confidence': .9} for c in candidates], 400
