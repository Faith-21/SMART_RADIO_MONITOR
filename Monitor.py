from faster_whisper import WhisperModel

# Initialize the model (using 'tiny' for speed or 'base' for better accuracy)
model_size = "base"
model = WhisperModel(model_size, device="cpu", compute_type="int8")

def transcribe_radio(audio_source):
    print(f"Monitoring source: {audio_source}...")
    segments, info = model.transcribe(audio_source, beam_size=5)

    print(f"Detected language '{info.language}' with probability {info.language_probability}")

    for segment in segments:
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")

if __name__ == "__main__":
    # You can replace this with a local path or a live stream URL
    source = "path_to_your_audio_file.mp3" 
    transcribe_radio(source)