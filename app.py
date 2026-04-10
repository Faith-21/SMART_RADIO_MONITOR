from flask import Flask, render_template, Response, request, stream_with_context
from transcriber import capture_and_transcribe
import json
import threading
import time
from datetime import datetime
import requests

app = Flask(__name__)

current_stream_url = None
is_running = False
transcript_lines = []

def transcription_loop():
    global is_running, transcript_lines
    while is_running:
        if current_stream_url:
            text = capture_and_transcribe(current_stream_url)
            if text:
                timestamp = time.strftime("%H:%M:%S")
                transcript_lines.append(f"[{timestamp}] {text}")
        time.sleep(1)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/proxy")
def proxy():
    """Proxy the radio stream through our server to bypass CORS."""
    url = request.args.get("url")
    if not url:
        return {"error": "No URL provided"}, 400

    try:
        req = requests.get(url, stream=True, timeout=10, headers={
            "User-Agent": "Mozilla/5.0",
            "Icy-MetaData": "1"
        })

        # Forward the audio stream
        def generate():
            try:
                for chunk in req.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            except Exception:
                pass

        # Detect content type
        content_type = req.headers.get("Content-Type", "audio/mpeg")

        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
                "X-Content-Type-Options": "nosniff",
            }
        )

    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/start", methods=["POST"])
def start():
    global current_stream_url, is_running, transcript_lines
    data = request.get_json()
    current_stream_url = data.get("url")
    transcript_lines = []
    if not is_running:
        is_running = True
        thread = threading.Thread(target=transcription_loop, daemon=True)
        thread.start()
    return {"status": "started"}

@app.route("/stop", methods=["POST"])
def stop():
    global is_running
    is_running = False
    return {"status": "stopped"}

@app.route("/transcript")
def transcript():
    return {"lines": transcript_lines}

@app.route("/export")
def export():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_slug = datetime.now().strftime("%Y%m%d_%H%M%S")

    content = f"SMART RADIO MONITOR — Transcript Export\n"
    content += f"Generated: {now}\n"
    content += f"Stream: {current_stream_url or 'Unknown'}\n"
    content += "=" * 60 + "\n\n"

    for line in transcript_lines:
        content += line + "\n\n"

    return Response(
        content,
        mimetype="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=transcript_{date_slug}.txt"
        }
    )

if __name__ == "__main__":
    app.run(debug=True)