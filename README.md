# Videogrep Web

A web GUI for searching video subtitles and creating supercuts. Uses SRT files for subtitles and ffmpeg for video processing.

## Features

- Upload multiple videos with their SRT subtitle files
- Search across all subtitles (plain text or regex)
- Preview matching clips in the browser
- Select results and export a supercut video
- Adjustable padding around clips

## Requirements

- Python 3.9+
- ffmpeg

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

## Usage

1. Click "Add Video" to upload a video file along with its `.srt` subtitle file
2. Type a search query and hit Search
3. Click "Preview" on any result to watch that clip
4. Check the clips you want, then click "Export Supercut" to download a combined video
