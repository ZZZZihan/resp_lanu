from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import wave

_PHRASE_NORMALIZER = re.compile(r"[\s，。！？；：、,.!?;:'\"“”‘’（）()\[\]{}<>《》]+")


@dataclass(frozen=True)
class PhraseHint:
    phrase: str
    aliases: frozenset[str]
    max_window: int


def _normalize_phrase(text: str) -> str:
    return _PHRASE_NORMALIZER.sub("", text)


def _read_grammar_file(path: str | Path | None) -> str | None:
    if path is None:
        return None
    grammar_obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(grammar_obj, list):
        return json.dumps(grammar_obj, ensure_ascii=False)
    raise ValueError("Grammar file must contain a JSON list of allowed phrases.")


def _read_phrase_hints(path: str | Path | None) -> list[PhraseHint]:
    if path is None:
        return []

    phrase_obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(phrase_obj, list):
        raise ValueError("Phrase hints file must contain a JSON list.")

    hints = []
    for index, item in enumerate(phrase_obj):
        if isinstance(item, str):
            phrase = _normalize_phrase(item)
            aliases: list[str] = []
        elif isinstance(item, dict):
            phrase = _normalize_phrase(str(item.get("phrase", "")))
            aliases = item.get("aliases", [])
            if aliases is None:
                aliases = []
            if not isinstance(aliases, list) or not all(isinstance(alias, str) for alias in aliases):
                raise ValueError(
                    f"Phrase hint at index {index} must use a string list for 'aliases'."
                )
        else:
            raise ValueError(
                f"Phrase hint at index {index} must be either a string or an object."
            )

        if not phrase:
            raise ValueError(f"Phrase hint at index {index} is missing a non-empty phrase.")

        normalized_aliases = {phrase}
        for alias in aliases:
            normalized = _normalize_phrase(alias)
            if normalized:
                normalized_aliases.add(normalized)

        max_window = min(max(len(alias) for alias in normalized_aliases), 8)
        hints.append(
            PhraseHint(
                phrase=phrase,
                aliases=frozenset(normalized_aliases),
                max_window=max_window,
            )
        )
    return hints


def apply_phrase_hints(
    transcript: str,
    words: list[dict],
    phrase_hints: list[PhraseHint],
) -> tuple[str, list[dict]]:
    if not transcript.strip() or not phrase_hints:
        return transcript, []

    raw_tokens = transcript.split()
    corrected_tokens: list[str] = []
    corrections: list[dict] = []
    index = 0

    while index < len(raw_tokens):
        best_match: tuple[PhraseHint, int, str] | None = None
        best_score: tuple[int, int] | None = None

        for hint in phrase_hints:
            max_window = min(hint.max_window, len(raw_tokens) - index)
            for window in range(max_window, 0, -1):
                candidate_tokens = raw_tokens[index : index + window]
                candidate_text = _normalize_phrase("".join(candidate_tokens))
                if candidate_text not in hint.aliases:
                    continue
                if candidate_text == hint.phrase and window == 1:
                    continue

                score = (window, len(hint.phrase))
                if best_score is None or score > best_score:
                    best_match = (hint, window, candidate_text)
                    best_score = score
                break

        if best_match is None:
            corrected_tokens.append(raw_tokens[index])
            index += 1
            continue

        hint, window, candidate_text = best_match
        original_tokens = raw_tokens[index : index + window]
        corrected_tokens.append(hint.phrase)

        confidences = [
            float(word["conf"])
            for word in words[index : index + window]
            if isinstance(word, dict) and isinstance(word.get("conf"), (int, float))
        ]
        correction = {
            "from": " ".join(original_tokens),
            "to": hint.phrase,
            "start_token": index,
            "end_token": index + window - 1,
            "match_type": "alias" if candidate_text != hint.phrase else "merge",
        }
        if confidences:
            correction["avg_conf"] = round(sum(confidences) / len(confidences), 6)
        corrections.append(correction)
        index += window

    return " ".join(corrected_tokens).strip(), corrections


def recognize_wav(
    model_path: str | Path,
    wav_path: str | Path,
    grammar_path: str | Path | None = None,
    phrase_hints_path: str | Path | None = None,
) -> dict:
    from vosk import KaldiRecognizer, Model

    wav_path = Path(wav_path)
    grammar = _read_grammar_file(grammar_path)
    phrase_hints = _read_phrase_hints(phrase_hints_path)

    with wave.open(str(wav_path), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError("Recognizer expects mono WAV input.")
        if wf.getsampwidth() != 2:
            raise ValueError("Recognizer expects 16-bit PCM WAV input.")
        if wf.getcomptype() != "NONE":
            raise ValueError("Recognizer expects uncompressed PCM WAV input.")

        model = Model(str(model_path))
        if grammar is None:
            recognizer = KaldiRecognizer(model, wf.getframerate())
        else:
            recognizer = KaldiRecognizer(model, wf.getframerate(), grammar)
        recognizer.SetWords(True)

        chunks = []
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            if recognizer.AcceptWaveform(data):
                chunk = json.loads(recognizer.Result())
                if chunk.get("text"):
                    chunks.append(chunk)

        final_chunk = json.loads(recognizer.FinalResult())
        if final_chunk.get("text"):
            chunks.append(final_chunk)

    transcript = " ".join(chunk["text"].strip() for chunk in chunks if chunk.get("text")).strip()
    word_items = []
    for chunk in chunks:
        word_items.extend(chunk.get("result", []))
    corrected_transcript, corrections = apply_phrase_hints(transcript, word_items, phrase_hints)
    return {
        "model_path": str(model_path),
        "wav_path": str(wav_path),
        "grammar_path": str(grammar_path) if grammar_path else None,
        "phrase_hints_path": str(phrase_hints_path) if phrase_hints_path else None,
        "num_chunks": len(chunks),
        "raw_transcript": transcript,
        "transcript": corrected_transcript,
        "corrections": corrections,
        "words": word_items,
    }
