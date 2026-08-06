YT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

YT_TABS = [
    "Home",
    "Video",
    "Shorts",
    "Live",
    "Podcast",
    "Corsi",
    "Playlist",
]

YT_TABS_URLS = [
    "featured",
    "videos",
    "shorts",
    "streams",
    "podcasts",
    "courses",
    "playlists",
]

YT_TAB_TO_URL = {
    "Home": "featured",
    "Video": "videos",
    "Shorts": "shorts",
    "Live": "streams",
    "Podcast": "podcasts",
    "Corsi": "courses",
    "Playlist": "playlists",
}

YT_URL_TO_TAB = {v: k for k, v in YT_TAB_TO_URL.items()}
