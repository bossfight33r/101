from __future__ import annotations

from pathlib import Path

from techstudio.schemas import Word


class FasterWhisperTranscriber:
    name = "faster_whisper"

    def __init__(self, model: str = "large-v3-turbo", device: str = "auto"):
        from faster_whisper import WhisperModel  # опциональная зависимость [asr]

        self.model = WhisperModel(model, device=device, compute_type="auto")

    def transcribe(self, audio: Path, *, language: str = "ru", hint: str = "") -> list[Word]:
        segments, _ = self.model.transcribe(
            str(audio), language=language, word_timestamps=True, initial_prompt=hint[:200] or None
        )
        words: list[Word] = []
        for seg in segments:
            for w in seg.words or []:
                words.append(
                    Word(text=w.word.strip(), start=w.start, end=w.end, prob=w.probability)
                )
        return words
