MESSAGES = {
    'invalid_url': 'Enter a valid YouTube video URL.',
    'too_long': 'This video is longer than 2 hours. Try a shorter video.',
    'video_unavailable': 'This video is unavailable or cannot be accessed.',
    'live_video': 'Live and upcoming videos are not supported. Try a recorded video.',
    'duration_unavailable': 'We couldn’t verify this video’s length. Please try again later.',
    'no_captions': 'No transcript is available for this video. Try another video.',
    'no_english': 'This video doesn’t have an available English transcript.',
    'empty_transcript': 'This video’s transcript doesn’t contain enough usable text.',
    'transcript_blocked': 'We couldn’t retrieve the transcript from YouTube right now. Please try again later.',
    'transcript_unavailable': 'Transcript retrieval is temporarily unavailable. Please try again.',
    'scoring_unavailable': 'Quote analysis is temporarily unavailable. Please try again.',
    'timeout': 'This analysis took too long. Please try again or choose a shorter video.',
    'limit_exceeded': 'This transcript is too large to analyse in one request. Try a shorter video.',
    'not_configured': 'Quote finding isn’t configured yet. The app owner needs to finish setup.',
    'rate_limited': 'You’ve reached the request limit. Please try again later.',
    'busy': 'Quote finding is busy right now. Please try again shortly.',
    'not_found': 'This analysis has expired or could not be found. Please submit the video again.',
    'cancelled': 'Analysis cancelled. You can try another video.',
    'internal': 'Something went wrong. Please try again.',
    'storage_unavailable': 'Quote finding is temporarily unavailable. Please try again.',
}


class AppError(Exception):
    def __init__(self, code, retryable=False, status=400):
        self.code, self.retryable, self.status = code, retryable, status
        super().__init__(MESSAGES[code])

    def payload(self):
        return {'code': self.code, 'message': str(self), 'retryable': self.retryable}
