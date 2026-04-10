from faster_whisper import WhisperModel
import os

# 1. Configuration
# 'base' is a good balance between speed and accuracy for local broadcasts.
MODEL_SIZE = "base"
# If you have a GPU, you can change device to "cuda"
DEVICE = "cpu" 
COMPUTE_TYPE = "int8"

def initialize_monitor():
    """Initializes the Whisper model for transcription."""
    print(f"Loading transcription model ({MODEL_SIZE})...")
    return WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)

def transcribe_audio(model, file_path):
    """Transcribes a specific audio file and prints the results."""
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found.")
        return

    print(f"Transcribing {file_path}...")
    segments, info = model.transcribe(file_path, beam_size=5)

    print(f"Detected language: {info.language} ({info.language_probability:.2f})")

    for segment in segments:
        print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")

if __name__ == "__main__":
    # Initialize the engine
    monitor_model = initialize_monitor()
    
    # Placeholder: Replace 'test_audio.mp3' with a recording from ZNBC or Radio Phoenix
    audio_to_process = "test_audio.mp3" 
    
    transcribe_audio(monitor_model, audio_to_process)