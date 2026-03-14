# Videogrep Web

A browser-based tool for searching video subtitles and creating supercuts. Inspired by [videogrep](https://github.com/antiboredom/videogrep). Uses ffmpeg for video processing and optionally Whisper for auto-transcription.

## Features

- **Multi-video support** — Upload multiple videos with SRT or VTT subtitle files and search across all of them
- **Flexible search** — Plain text or regex, with include/exclude filters
- **Multiple search terms** — Comma-separated terms with "any" (union) or "all" (intersect) matching
- **Sentence & fragment modes** — Search by full subtitle cue (sentence) or just the matching word/phrase (fragment) with estimated timestamps
- **Word-level VTT support** — Automatically detects word-level WebVTT files for precise fragment timestamps
- **Max results limit** — Cap the number of results returned for common words
- **Preview clips** — Preview individual clips or play all selected clips in sequence without exporting
- **Subtitle resync** — Per-video time offset to shift subtitles that are out of sync
- **Shuffle clips** — Randomize clip order before export
- **Multiple export formats:**
  - **Supercut (.mp4)** — Concatenated video of all selected clips
  - **Individual Clips (.zip)** — Each clip as a separate named .mp4 file
  - **EDL (.edl)** — Edit Decision List for import into professional NLEs
  - **FCPXML (.fcpxml)** — Final Cut Pro XML for import into FCP, DaVinci Resolve, and other editors (no re-encoding)
- **Word frequency explorer** — Browse the most common words and phrases across all loaded transcripts, then click to search
- **Whisper auto-transcription** — Upload a video without subtitles and transcribe it on the server using faster-whisper or openai-whisper
- **Adjustable padding** — Add extra seconds before/after each clip

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

### Optional: Whisper for auto-transcription

To enable transcription of videos without subtitle files, install one of:

**faster-whisper (recommended)** — faster, lower memory:
```bash
pip install faster-whisper
```

**openai-whisper** — the original OpenAI implementation:
```bash
pip install openai-whisper
```

The app auto-detects whichever is installed at startup. If neither is present, subtitle files are required for upload.

## Setup

```bash
# Clone the repo
git clone https://github.com/samplereality/videogrep-web.git
cd videogrep-web

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Optional: enable auto-transcription
pip install faster-whisper
```

## Running

```bash
source .venv/bin/activate        # if not already activated
python app.py
```

Open http://localhost:5001 in your browser.

To stop the server, press `Ctrl+C` in the terminal.

## Usage

### Upload

1. Click **+ Add Video** in the sidebar
2. Select a video file and its subtitle file (.srt or .vtt)
   - If Whisper is installed, the subtitle file is optional — a **Transcribe** button will appear next to the video
3. Uploaded videos appear in the sidebar with subtitle count and controls

### Search

1. Type a search query in the **Include** field and press **Search**
2. Use commas to search for multiple terms (e.g., `hello, goodbye`)
3. Choose **any term** (union) or **all terms** (intersect) with the mode dropdown
4. Use the **Exclude** field to filter out unwanted results (e.g., exclude a specific speaker)
5. Toggle **regex** for regular expression patterns
6. Switch between **sentence** (full subtitle cue) and **fragment** (just the matched word/phrase) modes
7. Set a **Max** value to limit the number of results (0 = no limit)

### Explore words

Click **Explore Words** to open the word frequency modal. Browse top words, 2-grams, and 3-grams across all loaded transcripts. Click any word to populate the search field and run a search.

### Preview

- Click **Preview** on any result row to watch that clip in the sidebar preview panel
- Click **Preview Selected** to play all checked clips in sequence — the app highlights each clip as it plays and shows a progress counter

### Subtitle resync

Each video in the sidebar has an **Offset** field (in seconds). Use this to shift all timestamps for that video — useful when subtitles are slightly out of sync. Positive values delay, negative values advance.

### Export

1. Check the clips you want (or use **Select All**)
2. Set **Padding** to add extra seconds before/after each clip
3. Check **Shuffle** to randomize the clip order
4. Choose an export **Format**:
   - **Supercut (.mp4)** — ffmpeg renders and concatenates all clips into one video
   - **Individual Clips (.zip)** — each clip is cut separately and bundled in a zip
   - **EDL (.edl)** — a text-based edit decision list for professional NLEs
   - **FCPXML (.fcpxml)** — XML timeline for Final Cut Pro and DaVinci Resolve (no re-encoding, just references to source media)
5. Click **Export** to generate and download

## Architecture

- **Backend:** Flask (Python), in-memory video store, ffmpeg for clip extraction
- **Frontend:** Single-page HTML/CSS/JS, no build step or dependencies
- **Whisper integration:** Optional, detected at startup, runs `base` model on CPU by default

## Credits

Inspired by [videogrep](https://github.com/antiboredom/videogrep) by Sam Lavigne.
