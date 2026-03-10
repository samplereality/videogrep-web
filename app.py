import os
import re
import json
import uuid
import subprocess
import tempfile
from flask import Flask, request, jsonify, send_from_directory, render_template

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
app.config["EXPORT_FOLDER"] = os.path.join(os.path.dirname(__file__), "exports")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["EXPORT_FOLDER"], exist_ok=True)

# In-memory store: {video_id: {name, video_path, srt_path, subtitles: [...]}}
videos = {}


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
        entries.append(
            {
                "start": start_str,
                "end": end_str,
                "start_seconds": timestamp_to_seconds(start_str),
                "end_seconds": timestamp_to_seconds(end_str),
                "text": text,
            }
        )
    return entries


def timestamp_to_seconds(ts):
    """Convert HH:MM:SS.mmm to seconds."""
    parts = ts.split(":")
    h, m = int(parts[0]), int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def upload():
    video_file = request.files.get("video")
    srt_file = request.files.get("srt")
    if not video_file or not srt_file:
        return jsonify({"error": "Both video and SRT files are required"}), 400

    video_id = str(uuid.uuid4())[:8]
    video_dir = os.path.join(app.config["UPLOAD_FOLDER"], video_id)
    os.makedirs(video_dir, exist_ok=True)

    video_path = os.path.join(video_dir, video_file.filename)
    srt_path = os.path.join(video_dir, srt_file.filename)
    video_file.save(video_path)
    srt_file.save(srt_path)

    subtitles = parse_srt(srt_path)
    videos[video_id] = {
        "name": video_file.filename,
        "video_path": video_path,
        "srt_path": srt_path,
        "subtitles": subtitles,
    }

    return jsonify({"id": video_id, "name": video_file.filename, "subtitle_count": len(subtitles)})


@app.route("/api/videos")
def list_videos():
    result = []
    for vid, info in videos.items():
        result.append({"id": vid, "name": info["name"], "subtitle_count": len(info["subtitles"])})
    return jsonify(result)


@app.route("/api/videos/<video_id>")
def get_video_info(video_id):
    if video_id not in videos:
        return jsonify({"error": "Video not found"}), 404
    info = videos[video_id]
    return jsonify({
        "id": video_id,
        "name": info["name"],
        "subtitles": info["subtitles"],
    })


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    video_ids = request.args.getlist("video_id")
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    use_regex = request.args.get("regex", "false").lower() == "true"
    results = []

    search_in = video_ids if video_ids else videos.keys()
    for vid in search_in:
        if vid not in videos:
            continue
        info = videos[vid]
        for i, sub in enumerate(info["subtitles"]):
            if use_regex:
                try:
                    if re.search(query, sub["text"], re.IGNORECASE):
                        results.append({**sub, "video_id": vid, "video_name": info["name"], "index": i})
                except re.error:
                    return jsonify({"error": "Invalid regex pattern"}), 400
            else:
                if query.lower() in sub["text"].lower():
                    results.append({**sub, "video_id": vid, "video_name": info["name"], "index": i})

    return jsonify({"query": query, "count": len(results), "results": results})


@app.route("/api/video/<video_id>/stream")
def stream_video(video_id):
    if video_id not in videos:
        return jsonify({"error": "Video not found"}), 404
    info = videos[video_id]
    directory = os.path.dirname(info["video_path"])
    filename = os.path.basename(info["video_path"])
    return send_from_directory(directory, filename)


@app.route("/api/export", methods=["POST"])
def export_supercut():
    data = request.get_json()
    if not data or "clips" not in data:
        return jsonify({"error": "clips array is required"}), 400

    clips = data["clips"]
    padding = float(data.get("padding", 0))
    export_id = str(uuid.uuid4())[:8]

    # Create a concat list file for ffmpeg
    clip_files = []
    try:
        for i, clip in enumerate(clips):
            vid = clip["video_id"]
            if vid not in videos:
                return jsonify({"error": f"Video {vid} not found"}), 404

            info = videos[vid]
            start = max(0, clip["start_seconds"] - padding)
            end = clip["end_seconds"] + padding
            duration = end - start

            clip_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_clip_{i}.mp4")
            clip_files.append(clip_path)

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", info["video_path"],
                "-t", str(duration),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "fast",
                "-avoid_negative_ts", "make_zero",
                clip_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode != 0:
                return jsonify({"error": f"ffmpeg failed on clip {i}: {result.stderr.decode()[-500:]}"}), 500

        # Concatenate all clips
        concat_list_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_list.txt")
        with open(concat_list_path, "w") as f:
            for cp in clip_files:
                f.write(f"file '{cp}'\n")

        output_path = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_supercut.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            return jsonify({"error": f"Concat failed: {result.stderr.decode()[-500:]}"}), 500

        return jsonify({"export_id": export_id, "filename": f"{export_id}_supercut.mp4"})

    finally:
        # Clean up individual clips and concat list
        for cp in clip_files:
            if os.path.exists(cp):
                os.remove(cp)
        list_file = os.path.join(app.config["EXPORT_FOLDER"], f"{export_id}_list.txt")
        if os.path.exists(list_file):
            os.remove(list_file)


@app.route("/api/export/<filename>")
def download_export(filename):
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(app.config["EXPORT_FOLDER"], filename, as_attachment=True)


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
