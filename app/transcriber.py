"""Faster-Whisper transcription wrapper."""

import json
import logging
from typing import Optional

from .models import Transcript

log = logging.getLogger(__name__)


class Transcriber:
    """Wrapper around faster-whisper for voice transcription."""

    def __init__(self, model_size: str = "base", language: Optional[str] = None,
                 device: str = "auto", compute_type: str = "default"):
        """
        Args:
            model_size: tiny/base/small/medium/large-v3
            language: ISO code (e.g. 'ru') or None for auto-detect
            device: 'cpu', 'cuda', or 'auto'
            compute_type: 'default', 'int8', 'float16', etc.
        """
        self.model_size = model_size
        self.language = language
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper is not installed. Install with: pip install faster-whisper"
            )
        log.info("Loading Whisper model '%s' (device=%s, compute=%s)...",
                 self.model_size, self.device, self.compute_type)
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        log.info("Whisper model loaded.")

    def transcribe(self, audio_path: str) -> Transcript:
        """Transcribe an audio file.

        Returns:
            Transcript dataclass with text and language.
        """
        self._load_model()

        log.info("Transcribing %s ...", audio_path)
        segments, info = self._model.transcribe(
            audio_path,
            language=self.language,
            beam_size=5,
            vad_filter=True,
        )

        language = info.language if info else (self.language or "unknown")
        all_segments = []
        full_text_parts = []

        for seg in segments:
            all_segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "probability": getattr(seg, "avg_logprob", None),
            })
            full_text_parts.append(seg.text.strip())

        text = " ".join(full_text_parts)
        segments_json = json.dumps(all_segments, ensure_ascii=False)

        # Compute average log prob
        avg_logprob = None
        if all_segments and "probability" in all_segments[0]:
            probs = [s.get("probability") for s in all_segments if s.get("probability") is not None]
            if probs:
                avg_logprob = sum(probs) / len(probs)

        log.info("Transcribed %s (%.1fs, %s, avg_logprob=%.3f)",
                 audio_path,
                 all_segments[-1]["end"] if all_segments else 0,
                 language,
                 avg_logprob or 0)

        return Transcript(
            media_id=0,  # Will be set by caller
            engine=f"faster-whisper/{self.model_size}",
            language=language,
            text=text,
            segments_json=segments_json,
        )
