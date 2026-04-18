from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Station(db.Model):
    __tablename__ = "stations"
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(200), nullable=False)
    stream_url = db.Column(db.String(500), nullable=False)
    country    = db.Column(db.String(100))
    genre      = db.Column(db.String(100))
    active     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    chunks      = db.relationship("AudioChunk", backref="station", lazy=True)
    transcripts = db.relationship("Transcript", backref="station", lazy=True)

class AudioChunk(db.Model):  
    __tablename__ = "audio_chunks"
    id         = db.Column(db.Integer, primary_key=True)
    station_id = db.Column(db.Integer, db.ForeignKey("stations.id"), nullable=False)
    file_path  = db.Column(db.String(500))
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time   = db.Column(db.DateTime)
    processed  = db.Column(db.Boolean, default=False)

    transcript = db.relationship("Transcript", backref="chunk", uselist=False)

class Transcript(db.Model):
    __tablename__ = "transcripts"
    id             = db.Column(db.Integer, primary_key=True)
    station_id     = db.Column(db.Integer, db.ForeignKey("stations.id"), nullable=False)
    chunk_id       = db.Column(db.Integer, db.ForeignKey("audio_chunks.id"))
    text           = db.Column(db.Text, nullable=False)
    language       = db.Column(db.String(50), default="en")
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    alerts = db.relationship("Alert", backref="transcript", lazy=True)

class Keyword(db.Model):
    __tablename__ = "keywords"
    id         = db.Column(db.Integer, primary_key=True)
    word       = db.Column(db.String(200), nullable=False, unique=True)
    active     = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Alert(db.Model):
    __tablename__ = "alerts"
    id            = db.Column(db.Integer, primary_key=True)
    keyword       = db.Column(db.String(200), nullable=False)
    transcript_id = db.Column(db.Integer, db.ForeignKey("transcripts.id"), nullable=False)
    matched_text  = db.Column(db.Text)
    station_name  = db.Column(db.String(200))
    sent_at       = db.Column(db.DateTime, default=datetime.utcnow)
    read          = db.Column(db.Boolean, default=False)