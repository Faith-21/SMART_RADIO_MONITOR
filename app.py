import os
import logging
import threading
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, Response, request, stream_with_context

from models import db, Station, AudioChunk, Transcript, Keyword, Alert, EmailRecipient, EmailConfig
from transcriber import capture_and_transcribe

load_dotenv()

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Database config ──
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DB_URL",
    "postgresql://postgres:password246@localhost:5432/smart_radio_monitor"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

db.init_app(app)

with app.app_context():
    db.create_all()
    logger.info("Database tables ready.")

# ── Multi-station state ──
active_stations  = {}
transcript_lines = []
transcript_lock  = threading.Lock()


def send_email_alert(keyword, station_name, matched_text):
    with app.app_context():
        config = EmailConfig.query.first()
        if not config or not config.enabled:
            return
        recipients = EmailRecipient.query.filter_by(active=True).all()
        if not recipients:
            return
        sender   = config.sender
        password = config.password

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            for r in recipients:
                msg = MIMEMultipart()
                msg["From"]    = sender
                msg["To"]      = r.email
                msg["Subject"] = f"Smart Radio Monitor — Keyword Detected: {keyword}"
                body = (
                    f"Smart Radio Monitor Alert\n\n"
                    f"Keyword:  {keyword}\n"
                    f"Station:  {station_name}\n"
                    f"Time:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"Transcript excerpt:\n{matched_text}\n\n---\nSmart Radio Monitor"
                )
                msg.attach(MIMEText(body, "plain"))
                server.sendmail(sender, r.email, msg.as_string())
        logger.info("Email alert sent for keyword: %s", keyword)
    except Exception as e:
        logger.error("Email failed: %s", e)


def detect_keywords(text, station_name, transcript_obj):
    keywords = Keyword.query.filter_by(active=True).all()
    for kw in keywords:
        if kw.word.lower() in text.lower():
            alert = Alert(
                keyword=kw.word,
                transcript_id=transcript_obj.id,
                matched_text=text,
                station_name=station_name,
            )
            db.session.add(alert)
            send_email_alert(kw.word, station_name, text)
    db.session.commit()


def transcription_worker(stream_url, station_name, stop_event):
    logger.info("Transcription worker started for '%s'", station_name)
    while not stop_event.is_set():
        try:
            text = capture_and_transcribe(stream_url)
            if text:
                timestamp = time.strftime("%H:%M:%S")
                line = f"[{timestamp}] [{station_name}] {text}"
                with transcript_lock:
                    transcript_lines.append(line)

                with app.app_context():
                    station = Station.query.filter_by(stream_url=stream_url).first()
                    if not station:
                        station = Station(name=station_name, stream_url=stream_url)
                        db.session.add(station)
                        db.session.commit()
                    elif station.name != station_name:
                        station.name = station_name
                        db.session.commit()

                    transcript = Transcript(station_id=station.id, text=text)
                    db.session.add(transcript)
                    db.session.commit()
                    detect_keywords(text, station_name, transcript)

        except Exception as e:
            logger.error(
                "Transcription error for '%s': %s", station_name, e, exc_info=True
            )
            stop_event.wait(5)  # Back off before retrying
            continue

        stop_event.wait(1)

    logger.info("Transcription worker stopped for '%s'", station_name)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/proxy")
def proxy():
    url = request.args.get("url")
    if not url:
        return {"error": "No URL provided"}, 400
    try:
        req = requests.get(url, stream=True, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "keep-alive",
            "Icy-MetaData": "0",
        })
        content_type = req.headers.get("Content-Type", "audio/mpeg")
        if "icy" in content_type.lower():
            content_type = "audio/mpeg"

        def generate():
            try:
                for chunk in req.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            except Exception:
                pass

        return Response(
            stream_with_context(generate()),
            content_type=content_type,
            direct_passthrough=True,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-cache",
                "Accept-Ranges": "none",
                "Transfer-Encoding": "chunked",
            },
        )
    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/start", methods=["POST"])
def start():
    global transcript_lines
    data         = request.get_json()
    stream_url   = data.get("url")
    station_name = data.get("name", "Unknown Station")

    if not stream_url:
        return {"error": "No URL"}, 400

    # Signal all running workers to stop
    for info in active_stations.values():
        info["stop_event"].set()
    active_stations.clear()

    transcript_lines = []
    stop_event = threading.Event()
    active_stations[stream_url] = {"stop_event": stop_event, "name": station_name}
    thread = threading.Thread(
        target=transcription_worker,
        args=(stream_url, station_name, stop_event),
        daemon=True,
    )
    active_stations[stream_url]["thread"] = thread
    thread.start()

    return {"status": "started", "station": station_name}


@app.route("/stop", methods=["POST"])
def stop():
    data = request.get_json() or {}
    url  = data.get("url")
    if url and url in active_stations:
        active_stations[url]["stop_event"].set()
        del active_stations[url]
    else:
        for info in active_stations.values():
            info["stop_event"].set()
        active_stations.clear()
    return {"status": "stopped"}


@app.route("/active_stations")
def get_active_stations():
    return {"stations": [
        {"url": url, "name": info["name"]}
        for url, info in active_stations.items()
        if not info["stop_event"].is_set()
    ]}


@app.route("/transcript")
def transcript():
    with transcript_lock:
        return {"lines": list(transcript_lines)}


@app.route("/export")
def export():
    now       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
    content   = "SMART RADIO MONITOR — Transcript Export\n"
    content  += f"Generated: {now}\n"
    content  += "=" * 60 + "\n\n"
    with transcript_lock:
        for line in transcript_lines:
            content += line + "\n\n"
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=transcript_{date_slug}.txt"},
    )


# ── Keywords ──
@app.route("/keywords", methods=["GET"])
def get_keywords():
    keywords = Keyword.query.filter_by(active=True).all()
    return {"keywords": [{"id": k.id, "word": k.word} for k in keywords]}


@app.route("/keywords", methods=["POST"])
def add_keyword():
    data = request.get_json()
    word = data.get("word", "").strip()
    if not word:
        return {"error": "No word provided"}, 400
    if Keyword.query.filter_by(word=word).first():
        return {"error": "Keyword already exists"}, 400
    keyword = Keyword(word=word)
    db.session.add(keyword)
    db.session.commit()
    return {"status": "added", "id": keyword.id, "word": keyword.word}


@app.route("/keywords/<int:kid>", methods=["DELETE"])
def delete_keyword(kid):
    keyword = Keyword.query.get_or_404(kid)
    db.session.delete(keyword)
    db.session.commit()
    return {"status": "deleted"}


# ── Alerts ──
@app.route("/alerts", methods=["GET"])
def get_alerts():
    alerts = Alert.query.order_by(Alert.sent_at.desc()).limit(50).all()
    return {"alerts": [{
        "id":           a.id,
        "keyword":      a.keyword,
        "station":      a.station_name,
        "matched_text": a.matched_text,
        "sent_at":      a.sent_at.strftime("%Y-%m-%d %H:%M:%S"),
        "read":         a.read,
    } for a in alerts]}


@app.route("/alerts/<int:aid>/read", methods=["POST"])
def mark_alert_read(aid):
    alert = Alert.query.get_or_404(aid)
    alert.read = True
    db.session.commit()
    return {"status": "marked as read"}


@app.route("/alerts/<int:aid>", methods=["DELETE"])
def delete_alert(aid):
    alert = Alert.query.get_or_404(aid)
    db.session.delete(alert)
    db.session.commit()
    return {"status": "deleted"}


@app.route("/alerts", methods=["DELETE"])
def delete_all_alerts():
    Alert.query.delete()
    db.session.commit()
    return {"status": "all deleted"}


# ── Transcript search ──
@app.route("/search")
def search():
    query      = request.args.get("q", "").strip()
    station_id = request.args.get("station")
    date_from  = request.args.get("from")
    date_to    = request.args.get("to")

    if not query and not station_id:
        return {"results": [], "total": 0}

    q = Transcript.query
    if query:
        q = q.filter(Transcript.text.ilike(f"%{query}%"))
    if station_id:
        q = q.filter(Transcript.station_id == station_id)
    if date_from:
        q = q.filter(Transcript.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        q = q.filter(Transcript.created_at <= datetime.strptime(date_to, "%Y-%m-%d"))

    results = q.join(Station).order_by(Transcript.created_at.desc()).limit(100).all()
    return {"results": [{
        "id":           r.id,
        "text":         r.text,
        "station_id":   r.station_id,
        "station_name": r.station.name,
        "created_at":   r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    } for r in results], "total": len(results)}


# ── Stations list ──
@app.route("/stations")
def get_stations():
    stations = Station.query.all()
    return {"stations": [{"id": s.id, "name": s.name} for s in stations]}


# ── Email config (persisted to DB) ──
@app.route("/email_config", methods=["GET"])
def get_email_config():
    config = EmailConfig.query.first()
    if not config:
        return {"enabled": False, "sender": ""}
    return {"enabled": config.enabled, "sender": config.sender}


@app.route("/email_config", methods=["POST"])
def set_email_config():
    data   = request.get_json()
    config = EmailConfig.query.first()
    if not config:
        config = EmailConfig()
        db.session.add(config)
    if "sender"   in data: config.sender   = data["sender"]
    if "password" in data: config.password = data["password"]
    if "enabled"  in data: config.enabled  = data["enabled"]
    db.session.commit()
    return {"status": "saved", "enabled": config.enabled}


# ── Email Recipients CRUD ──
@app.route("/email_recipients", methods=["GET"])
def get_recipients():
    recipients = EmailRecipient.query.all()
    return {"recipients": [{
        "id":     r.id,
        "email":  r.email,
        "name":   r.name,
        "active": r.active,
    } for r in recipients]}


@app.route("/email_recipients", methods=["POST"])
def add_recipient():
    data  = request.get_json()
    email = data.get("email", "").strip()
    name  = data.get("name",  "").strip()
    if not email:
        return {"error": "No email provided"}, 400
    if EmailRecipient.query.filter_by(email=email).first():
        return {"error": "Email already exists"}, 400
    recipient = EmailRecipient(email=email, name=name)
    db.session.add(recipient)
    db.session.commit()
    return {"status": "added", "id": recipient.id}


@app.route("/email_recipients/<int:rid>", methods=["PUT"])
def update_recipient(rid):
    recipient = EmailRecipient.query.get_or_404(rid)
    data = request.get_json()
    if "email"  in data: recipient.email  = data["email"].strip()
    if "name"   in data: recipient.name   = data["name"].strip()
    if "active" in data: recipient.active = data["active"]
    db.session.commit()
    return {"status": "updated"}


@app.route("/email_recipients/<int:rid>", methods=["DELETE"])
def delete_recipient(rid):
    recipient = EmailRecipient.query.get_or_404(rid)
    db.session.delete(recipient)
    db.session.commit()
    return {"status": "deleted"}


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
