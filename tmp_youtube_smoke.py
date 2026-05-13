from datetime import datetime
from jarvis.config import YOUTUBE_API_KEY
from jarvis.youtube_agent import process_youtube_url

print("key_set", bool(YOUTUBE_API_KEY))
result = process_youtube_url("https://www.youtube.com/watch?v=DCQNScSl4rU", datetime.now().isoformat())
print(result)
