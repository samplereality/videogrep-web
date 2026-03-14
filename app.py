import os
import re
import uuid
import random
import subprocess
import zipfile
from collections import Counter
from flask import Flask, request, jsonify, send_from_directory, render_template

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["EXPORT_FOLDER"] = os.path.join(os.path.dirname(__file__), "exports")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["EXPORT_FOLDER"], exist_ok=True)

# In-memory store: {video_id: {name, video_path, subtitle_path, subtitles, word_level, offset}}
videos = {}


# ---------------------------------------------------------------------------
# Whisper detection
# ---------------------------------------------------------------------------
def _detect_whisper():
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass
    try:
        import whisper  # noqa: F401
        return "openai-whisper"
    except ImportError:
        pass
    return None


WHISPER_BACKEND = _detect_whisper()


def _check_ffmpeg_drawtext():
    """Check if ffmpeg supports the drawtext filter."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-filters"], capture_output=True, timeout=10
        )
        return b"drawtext" in result.stdout
    except Exception:
        return False


HAS_DRAWTEXT = _check_ffmpeg_drawtext()


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def timestamp_to_seconds(ts):
    """Convert HH:MM:SS.mmm or MM:SS.mmm to seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        h, m = int(parts[0]), int(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s
    elif len(parts) == 2:
        m = int(parts[0])
        s = float(parts[1])
        return m * 60 + s
    return 0.0


def seconds_to_timestamp(seconds):
    """Convert seconds to HH:MM:SS.mmm string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def seconds_to_timecode(seconds, fps=24):
    """Convert seconds to HH:MM:SS:FF timecode for EDL."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s_int = int(seconds % 60)
    f = int(round((seconds % 1) * fps))
    if f >= fps:
        f = fps - 1
    return f"{h:02d}:{m:02d}:{s_int:02d}:{f:02d}"


def seconds_to_fcpxml_time(seconds, fps=24):
    """Convert seconds to FCPXML rational time (frames/fps)s."""
    frames = round(seconds * fps)
    return f"{frames}/{fps}s"


# ---------------------------------------------------------------------------
# Subtitle parsers
# ---------------------------------------------------------------------------
def _make_entry(start_str, end_str, text):
    return {
        "start": start_str,
        "end": end_str,
        "start_seconds": timestamp_to_seconds(start_str),
        "end_seconds": timestamp_to_seconds(end_str),
        "text": text,
    }


def parse_srt(filepath):
    """Parse an SRT file and return a list of subtitle entries."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    entries = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[1],
        )
        if not time_match:
            continue
        start_str = time_match.group(1).replace(",", ".")
        end_str = time_match.group(2).replace(",", ".")
        text = " ".join(lines[2:]).strip()
        entries.append(_make_entry(start_str, end_str, text))
    return entries


def parse_vtt(filepath):
    """Parse a WebVTT file and return a list of subtitle entries."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    entries = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue
        if lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue

        time_line_idx = None
        for j, line in enumerate(lines):
            if "-->" in line:
                time_line_idx = j
                break
        if time_line_idx is None:
            continue

        time_match = re.match(
            r"(\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{3})\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?[,\.]\d{3})",
            lines[time_line_idx],
        )
        if not time_match:
            continue
        start_str = time_match.group(1).replace(",", ".")
        end_str = time_match.group(2).replace(",", ".")

        text = " ".join(lines[time_line_idx + 1:]).strip()
        text = re.sub(r"<[^>]+>", "", text).strip()
        if not text:
            continue

        entries.append(_make_entry(start_str, end_str, text))
    return entries


def parse_subtitle_file(filepath):
    """Dispatch to the correct parser based on file extension."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".vtt":
        return parse_vtt(filepath)
    return parse_srt(filepath)


def is_word_level(entries):
    """Return True if the subtitle entries appear to be word-level (avg <= 2 words/cue)."""
    if not entries:
        return False
    avg = sum(len(e["text"].split()) for e in entries) / len(entries)
    return avg <= 2.0


def fragment_timestamps(sub, match, word_level=False):
    """Return precise start/end for a match within a subtitle cue."""
    if word_level:
        return sub["start_seconds"], sub["end_seconds"]
    text = sub["text"]
    duration = sub["end_seconds"] - sub["start_seconds"]
    if duration <= 0 or not text:
        return sub["start_seconds"], sub["end_seconds"]
    total = len(text)
    frag_start = sub["start_seconds"] + (match.start() / total) * duration
    frag_end = sub["start_seconds"] + (match.end() / total) * duration
    return frag_start, frag_end


# ---------------------------------------------------------------------------
# EDL / FCPXML generators
# ---------------------------------------------------------------------------
def generate_edl(clips, fps=24):
    """Generate a CMX 3600 EDL string."""
    lines = ["TITLE: Videogrep Supercut", "FCM: NON-DROP FRAME", ""]
    running_tc = 0.0
    for i, clip in enumerate(clips):
        vid = clip["video_id"]
        info = videos.get(vid, {})
        name = info.get("name", vid)
        start = clip["start_seconds"]
        end = clip["end_seconds"]
        duration = end - start

        src_in = seconds_to_timecode(start, fps)
        src_out = seconds_to_timecode(end, fps)
        rec_in = seconds_to_timecode(running_tc, fps)
        rec_out = seconds_to_timecode(running_tc + duration, fps)
        running_tc += duration

        edit_num = f"{i + 1:03d}"
        reel = vid[:8].ljust(8)
        lines.append(f"{edit_num}  {reel} V     C        {src_in} {src_out} {rec_in} {rec_out}")
        lines.append(f"* FROM CLIP NAME: {name}")
        if clip.get("text"):
            lines.append(f"* COMMENT: {clip['text']}")
        lines.append("")
    return "\n".join(lines)


def generate_fcpxml(clips, fps=24):
    """Generate an FCPXML 1.9 document string."""
    # Collect unique video assets
    asset_map = {}
    for clip in clips:
        vid = clip["video_id"]
        if vid not in asset_map:
            info = videos.get(vid, {})
            path = info.get("video_path", "")
            name = info.get("name", vid)
            asset_map[vid] = {"path": path, "name": name, "id": f"r{len(asset_map) + 2}"}

    total_duration = sum(c["end_seconds"] - c["start_seconds"] for c in clips)
    fmt_dur = seconds_to_fcpxml_time(total_duration, fps)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE fcpxml>',
        '<fcpxml version="1.9">',
        '    <resources>',
        f'        <format id="r1" frameDuration="{seconds_to_fcpxml_time(1 / fps, fps)}" width="1920" height="1080"/>',
    ]
    for vid, asset in asset_map.items():
        file_url = "file://" + asset["path"].replace(" ", "%20")
        lines.append(f'        <asset id="{asset["id"]}" src="{file_url}" start="0s" hasVideo="1" hasAudio="1" name="{asset["name"]}"/>')
    lines.append("    </resources>")
    lines.append("    <library>")
    lines.append('        <event name="Videogrep Supercut">')
    lines.append('            <project name="Supercut">')
    lines.append(f'                <sequence format="r1" duration="{fmt_dur}">')
    lines.append("                    <spine>")

    offset = 0.0
    for clip in clips:
        vid = clip["video_id"]
        asset = asset_map[vid]
        start = clip["start_seconds"]
        end = clip["end_seconds"]
        duration = end - start
        clip_text = clip.get("text", "")

        lines.append(
            f'                        <clip name="{clip_text[:40]}" '
            f'offset="{seconds_to_fcpxml_time(offset, fps)}" '
            f'duration="{seconds_to_fcpxml_time(duration, fps)}" '
            f'start="{seconds_to_fcpxml_time(start, fps)}">'
        )
        lines.append(
            f'                            <video ref="{asset["id"]}" '
            f'offset="{seconds_to_fcpxml_time(start, fps)}" '
            f'duration="{seconds_to_fcpxml_time(duration, fps)}"/>'
        )
        lines.append("                        </clip>")
        offset += duration

    lines.append("                    </spine>")
    lines.append("                </sequence>")
    lines.append("            </project>")
    lines.append("        </event>")
    lines.append("    </library>")
    lines.append("</fcpxml>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/capabilities")
def capabilities():
    """Report server capabilities so the frontend can show/hide features."""
    return jsonify({
        "whisper": WHISPER_BACKEND is not None,
        "whisper_backend": WHISPER_BACKEND,
        "burn_subtitles": HAS_DRAWTEXT,
    })


@app.route("/api/upload", methods=["POST"])
def upload():
    video_file = request.files.get("video")
    subtitle_file = request.files.get("srt")
    if not video_file:
        return jsonify({"error": "Video file is required"}), 400

    # Subtitle is optional if whisper is available
    if subtitle_file:
        ext = os.path.splitext(subtitle_file.filename)[1].lower()
        if ext not in (".srt", ".vtt"):
            return jsonify({"error": "Subtitle file must be .srt or .vtt"}), 400

    video_id = str(uuid.uuid4())[:8]
    video_dir = os.path.join(app.config["UPLOAD_FOLDER"], video_id)
    os.makedirs(video_dir, exist_ok=True)

    video_path = os.path.join(video_dir, video_file.filename)
    video_file.save(video_path)

    if subtitle_file:
        subtitle_path = os.path.join(video_dir, subtitle_file.filename)
        subtitle_file.save(subtitle_path)
        subtitles = parse_subtitle_file(subtitle_path)
        word_level = os.path.splitext(subtitle_file.filename)[1].lower() == ".vtt" and is_word_level(subtitles)
    else:
        subtitle_path = None
        subtitles = []
        word_level = False

    videos[video_id] = {
        "name": video_file.filename,
        "video_path": video_path,
        "subtitle_path": subtitle_path,
        "subtitles": subtitles,
        "word_level": word_level,
        "offset": 0.0,
    }

    return jsonify({
        "id": video_id,
        "name": video_file.filename,
        "subtitle_count": len(subtitles),
        "word_level": word_level,
        "needs_transcription": subtitle_path is None,
    })


@app.route("/api/videos")
def list_videos():
    result = []
    for vid, info in videos.items():
        result.append({
            "id": vid,
            "name": info["name"],
            "subtitle_count": len(info["subtitles"]),
            "word_level": info.get("word_level", False),
            "offset": info.get("offset", 0.0),
            "needs_transcription": info.get("subtitle_path") is None and len(info["subtitles"]) == 0,
        })
    return jsonify(result)


@app.route("/api/videos/<video_id>")
def get_video_info(video_id):
    if video_id not in videos:
        return jsonify({"error": "Video not found"}), 404
    info = videos[video_id]
    return jsonify({
        "id": video_id,
        "name": info["name"],
        "word_level": info.get("word_level", False),
        "offset": info.get("offset", 0.0),
        "subtitles": info["subtitles"],
    })


@app.route("/api/videos/<video_id>/offset", methods=["POST"])
def set_offset(video_id):
    """Set a time offset (in seconds) for a video's subtitles."""
    if video_id not in videos:
        return jsonify({"error": "Video not found"}), 404
    data = request.get_json()
    offset = float(data.get("offset", 0))
    videos[video_id]["offset"] = offset
    return jsonify({"ok": True, "offset": offset})


@app.route("/api/videos/<video_id>", methods=["DELETE"])
def delete_video(video_id):
    if video_id not in videos:
        return jsonify({"error": "Video not found"}), 404
    import shutil
    video_dir = os.path.join(app.config["UPLOAD_FOLDER"], video_id)
    if os.path.exists(video_dir):
        shutil.rmtree(video_dir)
    del videos[video_id]
    return jsonify({"ok": True})


@app.route("/api/video/<video_id>/stream")
def stream_video(video_id):
    if video_id not in videos:
        return jsonify({"error": "Video not found"}), 404
    info = videos[video_id]
    directory = os.path.dirname(info["video_path"])
    filename = os.path.basename(info["video_path"])
    return send_from_directory(directory, filename)


# ---------------------------------------------------------------------------
# Search (supports multi-term, any/all mode, max limit, offset)
# ---------------------------------------------------------------------------
@app.route("/api/search")
def search():
    raw_query = request.args.get("q", "").strip()
    if not raw_query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    # Split comma-separated terms
    terms = [t.strip() for t in raw_query.split(",") if t.strip()]
    mode = request.args.get("mode", "any")  # "any" (union) or "all" (intersect)
    if mode not in ("any", "all"):
        mode = "any"

    exclude = request.args.get("exclude", "").strip()
    search_type = request.args.get("type", "sentence")
    if search_type not in ("sentence", "fragment"):
        return jsonify({"error": "type must be 'sentence' or 'fragment'"}), 400

    use_regex = request.args.get("regex", "false").lower() == "true"
    limit = request.args.get("limit", 0, type=int)
    video_ids = request.args.getlist("video_id")

    results = []
    search_in = video_ids if video_ids else list(videos.keys())

    for vid in search_in:
        if vid not in videos:
            continue
        info = videos[vid]
        word_level = info.get("word_level", False)
        offset = info.get("offset", 0.0)

        for i, sub in enumerate(info["subtitles"]):
            text = sub["text"]

            # Check exclude first
            if exclude:
                if use_regex:
                    try:
                        if re.search(exclude, text, re.IGNORECASE):
                            continue
                    except re.error:
                        pass
                else:
                    if exclude.lower() in text.lower():
                        continue

            # Check each term
            term_matches = []
            for term in terms:
                if use_regex:
                    try:
                        m = re.search(term, text, re.IGNORECASE)
                        if m:
                            term_matches.append(m)
                    except re.error as e:
                        return jsonify({"error": f"Invalid regex: {e}"}), 400
                else:
                    m = re.search(re.escape(term), text, re.IGNORECASE)
                    if m:
                        term_matches.append(m)

            # Apply mode logic
            if mode == "all" and len(term_matches) != len(terms):
                continue
            if mode == "any" and len(term_matches) == 0:
                continue

            # Use first match for fragment positioning
            match = term_matches[0]
            entry = {**sub, "video_id": vid, "video_name": info["name"], "index": i}
            entry["start_seconds"] = sub["start_seconds"] + offset
            entry["end_seconds"] = sub["end_seconds"] + offset

            if search_type == "fragment":
                frag_start, frag_end = fragment_timestamps(sub, match, word_level)
                entry["start_seconds"] = frag_start + offset
                entry["end_seconds"] = frag_end + offset

            results.append(entry)

            if 0 < limit <= len(results):
                break
        if 0 < limit <= len(results):
            break

    return jsonify({
        "query": raw_query,
        "terms": terms,
        "mode": mode,
        "exclude": exclude,
        "type": search_type,
        "count": len(results),
        "results": results,
    })


# ---------------------------------------------------------------------------
# N-grams / word frequency
# ---------------------------------------------------------------------------
STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "it", "its", "this", "that", "i", "you",
    "he", "she", "we", "they", "my", "your", "his", "her", "our", "their",
    "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may", "might",
    "can", "shall", "so", "if", "not", "no", "just", "then", "than",
    "too", "very", "about", "up", "out", "what", "which", "who", "when",
    "where", "how", "all", "each", "every", "some", "any", "few", "more",
    "most", "other", "into", "from", "as", "are", "am", "me", "him",
    "them", "us", "like", "know", "think", "going", "yeah", "oh", "uh",
    "um", "okay", "well", "got", "get", "go", "one", "two", "don",
    "t", "s", "re", "ve", "ll", "d", "m",
})


@app.route("/api/ngrams")
def ngrams():
    n = request.args.get("n", 1, type=int)
    top = request.args.get("top", 50, type=int)
    video_ids = request.args.getlist("video_id")
    n = max(1, min(n, 4))
    top = max(1, min(top, 200))

    search_in = video_ids if video_ids else list(videos.keys())
    counter = Counter()

    for vid in search_in:
        if vid not in videos:
            continue
        for sub in videos[vid]["subtitles"]:
            words = re.findall(r"[a-zA-Z']+", sub["text"].lower())
            # Strip possessives
            words = [w.strip("'") for w in words if w.strip("'")]
            if n == 1:
                for w in words:
                    if w not in STOP_WORDS and len(w) > 1:
                        counter[w] += 1
            else:
                for j in range(len(words) - n + 1):
                    gram_words = words[j:j + n]
                    gram = " ".join(gram_words)
                    if not all(w in STOP_WORDS for w in gram_words):
                        counter[gram] += 1

    results = [{"text": text, "count": count} for text, count in counter.most_common(top)]
    return jsonify({"n": n, "total_unique": len(counter), "results": results})


# ---------------------------------------------------------------------------
# Export (supercut, individual clips zip, EDL, FCPXML)
# ---------------------------------------------------------------------------
@app.route("/api/export", methods=["POST"])
def export_supercut():
    data = request.get_json()
    if not data or "clips" not in data:
        return jsonify({"error": "clips array is required"}), 400

    clips = data["clips"]
    padding = float(data.get("padding", 0))
    shuffle = data.get("shuffle", False)
    burn_subs = data.get("burn_subtitles", False)
    fmt = data.get("format", "supercut")  # supercut | clips | edl | fcpxml

    if shuffle:
        clips = list(clips)
        random.shuffle(clips)

    # Apply padding to clip timestamps
    if padding > 0:
        clips = [
            {**c,
             "start_seconds": max(0, c["start_seconds"] - padding),
             "end_seconds": c["end_seconds"] + padding}
            for c in clips
        ]

    export_id = str(uuid.uuid4())[:8]

    # --- Text-based formats (no ffmpeg) ---
    if fmt == "edl":
        content = generate_edl(clips)
        out_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_supercut.edl")
        with open(out_path, "w") as f:
            f.write(content)
        return jsonify({"export_id": export_id, "filename": f"{export_id}_supercut.edl"})

    if fmt == "fcpxml":
        content = generate_fcpxml(clips)
        out_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_supercut.fcpxml")
        with open(out_path, "w") as f:
            f.write(content)
        return jsonify({"export_id": export_id, "filename": f"{export_id}_supercut.fcpxml"})

    # --- Video-based formats: cut clips with ffmpeg ---
    clip_files = []
    try:
        for i, clip in enumerate(clips):
            vid = clip["video_id"]
            if vid not in videos:
                return jsonify({"error": f"Video {vid} not found"}), 404

            info = videos[vid]
            start = clip["start_seconds"]
            end = clip["end_seconds"]
            duration = max(0.1, end - start)

            clip_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_clip_{i}.mp4")
            clip_files.append(clip_path)

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", info["video_path"],
                "-t", str(duration),
            ]

            sub_textfiles = []
            if burn_subs and HAS_DRAWTEXT and clip.get("text"):
                # Word-wrap long lines at ~40 chars
                raw = clip["text"]
                words = raw.split()
                lines = []
                current = ""
                for w in words:
                    if current and len(current) + 1 + len(w) > 40:
                        lines.append(current)
                        current = w
                    else:
                        current = current + " " + w if current else w
                if current:
                    lines.append(current)

                # Use one drawtext filter per line to avoid newline
                # rendering as block glyphs.  Each line gets its own
                # temp file and is positioned from the bottom up.
                line_height = 30  # fontsize(24) + spacing
                base_y = 40       # distance from bottom for lowest line
                filters = []
                for li, line_text in enumerate(reversed(lines)):
                    tf_path = os.path.join(
                        app.config["EXPORT_FOLDER"],
                        f"{export_id}_txt_{i}_{li}.txt",
                    )
                    with open(tf_path, "w", encoding="utf-8") as tf:
                        tf.write(line_text)
                    sub_textfiles.append(tf_path)
                    tf_esc = tf_path.replace("\\", "/").replace(":", "\\:")
                    y_pos = base_y + li * line_height
                    filters.append(
                        f"drawtext=textfile='{tf_esc}'"
                        f":fontsize=24:fontcolor=white:borderw=2:bordercolor=black"
                        f":x=(w-text_w)/2:y=h-th-{y_pos}"
                    )
                cmd += ["-vf", ",".join(filters)]

            cmd += [
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "fast",
                "-avoid_negative_ts", "make_zero",
                clip_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                stderr = result.stderr.decode()
                if burn_subs and ("No such filter" in stderr or "Filter not found" in stderr):
                    return jsonify({"error": "Burn-in subtitles requires ffmpeg with libfreetype or libass. Run: brew reinstall ffmpeg"}), 400
                return jsonify({"error": f"ffmpeg failed on clip {i}: {stderr[-500:]}"}), 500

        if fmt == "clips":
            # Zip individual clips
            zip_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_clips.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, cp in enumerate(clip_files):
                    text_slug = re.sub(r"[^a-zA-Z0-9]+", "_", clips[i].get("text", "")[:30]).strip("_") or f"clip"
                    zf.write(cp, f"{i + 1:03d}_{text_slug}.mp4")
            return jsonify({"export_id": export_id, "filename": f"{export_id}_clips.zip"})

        # Default: concatenate into supercut
        concat_list_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_list.txt")
        with open(concat_list_path, "w") as f:
            for cp in clip_files:
                f.write(f"file '{cp}'\n")

        output_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_supercut.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
        ]

        # If burn_subs requested but no drawtext, mux a combined SRT into the final supercut
        srt_combined = None
        if burn_subs and not HAS_DRAWTEXT:
            srt_combined = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_subs.srt")
            running = 0.0
            with open(srt_combined, "w", encoding="utf-8") as sf:
                for idx, clip in enumerate(clips):
                    clip_dur = clip["end_seconds"] - clip["start_seconds"]
                    text = clip.get("text", "")
                    if text:
                        start_ts = seconds_to_timestamp(running).replace(".", ",")
                        end_ts = seconds_to_timestamp(running + clip_dur).replace(".", ",")
                        sf.write(f"{idx + 1}\n{start_ts} --> {end_ts}\n{text}\n\n")
                    running += clip_dur
            cmd += ["-i", srt_combined,
                    "-map", "0:v", "-map", "0:a", "-map", "1:s",
                    "-c:v", "libx264", "-c:a", "aac", "-c:s", "mov_text",
                    "-preset", "fast",
                    "-metadata:s:s:0", "language=eng"]
        else:
            cmd += ["-c:v", "libx264", "-c:a", "aac", "-preset", "fast"]

        cmd.append(output_path)
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if srt_combined and os.path.exists(srt_combined):
            os.remove(srt_combined)
        if result.returncode != 0:
            return jsonify({"error": f"Concat failed: {result.stderr.decode()[-500:]}"}), 500

        return jsonify({"export_id": export_id, "filename": f"{export_id}_supercut.mp4"})

    finally:
        for cp in clip_files:
            if os.path.exists(cp):
                os.remove(cp)
        list_file = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_list.txt")
        if os.path.exists(list_file):
            os.remove(list_file)
        # Clean up temp subtitle text files from drawtext
        import glob as _glob
        for tf in _glob.glob(os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_txt_*")):
            os.remove(tf)


@app.route("/api/export/<filename>")
def download_export(filename):
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(app.config["EXPORT_FOLDER"], filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Whisper transcription
# ---------------------------------------------------------------------------
@app.route("/api/transcribe/<video_id>", methods=["POST"])
def transcribe(video_id):
    if video_id not in videos:
        return jsonify({"error": "Video not found"}), 404
    if not WHISPER_BACKEND:
        return jsonify({"error": "Whisper is not installed. Install faster-whisper or openai-whisper."}), 400

    info = videos[video_id]
    video_path = info["video_path"]

    data = request.get_json() or {}
    model_size = data.get("model", "base")

    try:
        subtitles = []
        if WHISPER_BACKEND == "faster-whisper":
            from faster_whisper import WhisperModel
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(video_path)
            for seg in segments:
                subtitles.append({
                    "start": seconds_to_timestamp(seg.start),
                    "end": seconds_to_timestamp(seg.end),
                    "start_seconds": seg.start,
                    "end_seconds": seg.end,
                    "text": seg.text.strip(),
                })
        else:
            import whisper
            model = whisper.load_model(model_size)
            result = model.transcribe(video_path)
            for seg in result["segments"]:
                subtitles.append({
                    "start": seconds_to_timestamp(seg["start"]),
                    "end": seconds_to_timestamp(seg["end"]),
                    "start_seconds": seg["start"],
                    "end_seconds": seg["end"],
                    "text": seg["text"].strip(),
                })

        info["subtitles"] = subtitles
        info["word_level"] = is_word_level(subtitles)
        return jsonify({"subtitle_count": len(subtitles), "word_level": info["word_level"]})

    except Exception as e:
        return jsonify({"error": f"Transcription failed: {e}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
