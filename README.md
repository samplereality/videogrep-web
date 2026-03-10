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
- [ffmpeg](https://ffmpeg.org/download.html)

### Installing ffmpeg

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg
```

**Windows:**
Download from https://ffmpeg.org/download.html and add to your PATH.

## Setup

```bash
# Clone the repo
git clone https://github.com/samplereality/videogrep-web.git
cd videogrep-web

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

## Running

```bash
source venv/bin/activate        # if not already activated
python app.py
```

Open http://localhost:5000 in your browser.

To stop the server, press `Ctrl+C` in the terminal.

## Usage

1. Click **Add Video** in the sidebar to upload a video file along with its `.srt` subtitle file
2. Type a search query and hit **Search** (check "regex" for regular expression support)
3. Click **Preview** on any result to watch that clip in the browser
4. Check the clips you want, then click **Export Supercut** to download a combined video
5. Use the **Padding** control to add extra seconds before/after each clip
