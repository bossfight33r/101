from __future__ import annotations

from pathlib import Path

from techstudio.schemas import Word


class MlxWhisperTranscriber:
    name = "mlx"

    def __init__(self, model: str = "mlx-community/whisper-large-v3-turbo"):
        import mlx_whisper  # только Apple Silicon

        self._mlx = mlx_whisper
        self.model = model

    def transcribe(self, audio: Path, *, language: str = "ru", hint: str = "") -> list[Word]:
        out = self._mlx.transcribe(
            str(audio), path_or_hf_repo=self.model, language=language, word_timestamps=True
        )
        return [
            Word(
                text=w["word"].strip(), start=w["start"], end=w["end"], prob=w.get("probability", 1)
            )
            for seg in out.get("segments", [])
            for w in seg.get("words", [])
        ]
