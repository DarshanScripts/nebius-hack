"""Cross-model invariants shared by the API, standalone modules and renderer client.

These helpers raise ValueError. Stage adapters should translate violations to a
StageFailure; the coordinator also validates outputs before publishing them.
"""
import hashlib
import json
import re
import wave
from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from contracts.models import (
    AlignmentResult, ArtifactRef, AudioBundle, CharacterSpec, DialogueScript, ImageBundle,
    ResearchBundle, SceneBuild, SceneContext, SceneSlot, Timeline, RenderResult,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_json(value) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_hash(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def artifact_path(root: Path, key: str) -> Path:
    require(bool(key) and "\\" not in key and "\x00" not in key, "Invalid artifact key")
    parts = PurePosixPath(key)
    require(not parts.is_absolute() and all(p not in (".", "..", "") for p in key.split("/")),
            "Artifact key must be a normalized relative path")
    root = root.resolve()
    path = (root / key).resolve()
    require(path.is_relative_to(root) and path != root, "Artifact escapes root")
    return path


def verify_artifact(root: Path, ref: ArtifactRef) -> Path:
    require(bool(re.fullmatch(r"[0-9a-f]{64}", ref.sha256)), "Invalid SHA-256")
    path = artifact_path(root, ref.key)
    require(path.is_file(), f"Missing artifact: {ref.key}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    require(path.stat().st_size == ref.size_bytes and digest.hexdigest() == ref.sha256,
            f"Artifact integrity mismatch: {ref.key}")
    return path


def validate_artifacts(value, root: Path, project_id: str) -> None:
    """Recursive verification, including project isolation for every reference."""
    if isinstance(value, ArtifactRef):
        require(value.key.startswith(f"projects/{project_id}/"), "Cross-project artifact")
        verify_artifact(root, value)
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            validate_artifacts(getattr(value, name), root, project_id)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_artifacts(item, root, project_id)
    elif isinstance(value, dict):
        for item in value.values():
            validate_artifacts(item, root, project_id)


def unique(values, label: str) -> set:
    values = list(values)
    require(len(values) == len(set(values)), f"Duplicate {label}")
    return set(values)


def validate_characters(characters: list[CharacterSpec]) -> None:
    require(len(characters) == 2 and {c.character_id for c in characters} == {"sundar", "jensen"},
            "Require exactly Sundar and Jensen character mappings")


def validate_research(research: ResearchBundle) -> None:
    sources = unique((s.source_id for s in research.sources), "source IDs")
    unique((c.claim_id for c in research.claims), "claim IDs")
    require(bool(research.summary.strip()) and bool(research.report_markdown.strip()), "Empty research")
    require(bool(research.claims), "Research has no citable claims")
    for claim in research.claims:
        require(set(claim.source_ids) <= sources, "Unknown claim source")
        require(claim.evidence_type != "inference" or bool((claim.caveat or "").strip()),
                "Inference requires a caveat")


def validate_script(script: DialogueScript, research: ResearchBundle) -> None:
    require(script.project_id == research.project_id, "Script project mismatch")
    claims = {c.claim_id for c in research.claims}
    require([t.order for t in script.turns] == list(range(1, 13)), "Turn order must be 1..12")
    for index, turn in enumerate(script.turns, 1):
        require(turn.dialogue_id == f"d{index:03}", "Noncanonical dialogue ID")
        require(turn.scene_index == (index - 1) // 2 + 1, "Wrong dialogue scene")
        require(turn.speaker_id == ("sundar" if index % 2 else "jensen"), "Speakers must alternate")
        require(set(turn.claim_ids) <= claims, "Unknown dialogue claim")
        require(bool(turn.text.strip()), "Empty dialogue")
        require(turn.intent == "question" or turn.text.rstrip().endswith("?") or bool(turn.claim_ids),
                "Factual answer/challenge/takeaway requires claims")


def validate_images(images: ImageBundle, script: DialogueScript) -> None:
    require(images.project_id == script.project_id and images.script_revision == script.script_revision,
            "Image project/revision mismatch")
    require(sorted(s.query.scene_index for s in images.selections) == list(range(1, 7)),
            "Images must cover all six scenes once")
    for selection in images.selections:
        ids = [t.dialogue_id for t in script.turns if t.scene_index == selection.query.scene_index]
        require(selection.query.dialogue_ids == ids, "Image query dialogue mismatch")
        if selection.status == "selected":
            require(selection.asset is not None and bool(selection.image_url), "Selected image lacks asset/URL")
        else:
            require(selection.asset is None and bool(selection.reason), "Unavailable image requires a reason")


def validate_audio(audio: AudioBundle, script: DialogueScript, *, live: bool = False,
                   root: Path | None = None) -> None:
    require(audio.project_id == script.project_id and audio.script_revision == script.script_revision,
            "Audio project/revision mismatch")
    clips = {u.dialogue_id: u for u in audio.utterances}
    require(len(clips) == 12 and set(clips) == {t.dialogue_id for t in script.turns},
            "Require exactly one clip for each turn")
    require(audio.total_speech_frames == sum(u.frame_count for u in clips.values()), "Wrong speech total")
    require(audio.total_speech_frames <= 1599, "AUDIO_DURATION_OUT_OF_RANGE: speech exceeds 1599 frames")
    all_words = []
    for turn in script.turns:
        clip = clips[turn.dialogue_id]
        require(clip.speaker_id == turn.speaker_id and clip.transcript == turn.text,
                "Audio speaker/transcript mismatch")
        require(clip.sample_count == clip.frame_count * 1600, "WAV must be frame padded")
        require(clip.duration_ms == round(clip.sample_count * 1000 / 48000), "Incorrect audio duration")
        require(not live or clip.timing_quality != "mock", "Mock timings cannot enter live context")
        last_end = 0
        for index, word in enumerate(clip.words, 1):
            require(word.word_id == f"{clip.dialogue_id}_w{index:03}", "Noncanonical word ID")
            require(last_end <= word.start_ms < word.end_ms <= clip.duration_ms, "Invalid word interval")
            require(bool(word.text.strip()), "Empty aligned word")
            last_end = word.end_ms
            all_words.append(word.word_id)
        # Tokenization and punctuation may differ; meaningful spoken tokens must survive alignment.
        normalize = lambda text: "".join(re.findall(r"\w+", text.casefold()))
        require(normalize(" ".join(w.text for w in clip.words)) == normalize(turn.text),
                "ALIGNMENT_INCOMPLETE: aligned words do not cover transcript")
        if root is not None:
            with wave.open(str(verify_artifact(root, clip.wav)), "rb") as stream:
                require((stream.getframerate(), stream.getnchannels(), stream.getsampwidth(), stream.getnframes())
                        == (48000, 1, 2, clip.sample_count), "WAV format/sample count mismatch")
            alignment = AlignmentResult.model_validate_json(verify_artifact(root, clip.words_file).read_bytes())
            require(alignment.dialogue_id == clip.dialogue_id and alignment.audio_sha256 == clip.wav.sha256
                    and alignment.transcript == clip.transcript and alignment.words == clip.words,
                    "Alignment file does not describe the canonical audio/words")
            require(verify_artifact(root, clip.transcript_file).read_text().strip() == clip.transcript,
                    "Transcript file does not match dialogue")
    unique(all_words, "word IDs")


def validate_timeline(timeline: Timeline, script: DialogueScript, audio: AudioBundle) -> None:
    require(timeline.project_id == script.project_id and timeline.script_revision == script.script_revision,
            "Timeline project/revision mismatch")
    clips = {u.dialogue_id: u for u in audio.utterances}
    require([u.dialogue_id for u in timeline.utterances] == [t.dialogue_id for t in script.turns],
            "Timeline dialogue order mismatch")
    cursor = 15
    for index, utterance in enumerate(timeline.utterances):
        require(utterance.start_frame == cursor and
                utterance.end_frame == cursor + clips[utterance.dialogue_id].frame_count,
                "Timeline utterance placement mismatch")
        cursor = utterance.end_frame + (6 if index % 2 == 0 else 24)
    require(timeline.utterances[-1].end_frame <= 1770, "Missing trailing silence")
    boundaries = [0] + [timeline.utterances[i].end_frame + 12 for i in (1, 3, 5, 7, 9)] + [1800]
    require([s.index for s in timeline.scenes] == list(range(1, 7)), "Scene order mismatch")
    for i, slot in enumerate(timeline.scenes):
        require(slot.scene_id == f"s{i + 1:02}" and
                (slot.start_frame, slot.end_frame) == (boundaries[i], boundaries[i + 1]),
                "Scene coverage/boundary mismatch")
        require(slot.dialogue_ids == [t.dialogue_id for t in script.turns[2*i:2*i+2]], "Scene turn mismatch")
        require(all(slot.start_frame <= u.start_frame < u.end_frame <= slot.end_frame
                    for u in timeline.utterances[2*i:2*i+2]), "Speech outside scene")


def validate_context(context: SceneContext, *, live: bool = False, root: Path | None = None) -> None:
    for bundle in (context.research, context.script, context.images, context.audio, context.timeline):
        require(bundle.project_id == context.project_id, "Context contains a different project")
    validate_characters(context.characters)
    validate_research(context.research)
    validate_script(context.script, context.research)
    validate_images(context.images, context.script)
    validate_audio(context.audio, context.script, live=live, root=root)
    validate_timeline(context.timeline, context.script, context.audio)
    require(not live or not context.research.is_mock, "Mock research cannot enter live context")
    require(context.timeline_hash == canonical_hash(context.timeline), "Timeline hash mismatch")
    payload = context.model_dump(mode="json", exclude={"context_hash"})
    require(context.context_hash == canonical_hash(payload), "Context hash mismatch")
    if root is not None:
        validate_artifacts(context, root, context.project_id)


def validate_build(build: SceneBuild, context: SceneContext, slot: SceneSlot, revision: int) -> None:
    require(build.project_id == context.project_id and build.scene_id == slot.scene_id
            and build.revision == revision, "Scene build identity mismatch")
    require(build.context_hash == context.context_hash and build.timeline_hash == context.timeline_hash,
            "Scene build context/timeline mismatch")
    words = {w.word_id for clip in context.audio.utterances if clip.dialogue_id in slot.dialogue_ids
             for w in clip.words}
    claims = {c.claim_id for c in context.research.claims}
    unique((c.cue_id for c in build.cues), "cue IDs")
    for cue in build.cues:
        require(0 <= cue.start_frame < cue.end_frame <= slot.end_frame - slot.start_frame,
                "Cue outside scene")
        require(set(cue.word_ids) <= words and set(cue.claim_ids) <= claims, "Cue reference mismatch")
        if cue.word_ids:
            starts, ends = [], []
            for clip in context.audio.utterances:
                global_start = next(u.start_frame for u in context.timeline.utterances
                                    if u.dialogue_id == clip.dialogue_id)
                for word in clip.words:
                    if word.word_id in cue.word_ids:
                        starts.append(global_start + word.start_ms * 30 // 1000 - slot.start_frame)
                        ends.append(global_start + (word.end_ms * 30 + 999) // 1000 - slot.start_frame)
            require(cue.start_frame == min(starts) and cue.end_frame == max(ends),
                    "Word cue must use authoritative aligned frames")


def validate_render(result: RenderResult, project_id: str, frames: int) -> None:
    require(result.project_id == project_id, "Render project mismatch")
    require(result.status == "completed" and result.video is not None and result.error is None,
            "Render did not complete successfully")
    require(result.duration_frames == frames and result.progress == 1, "Render duration/progress mismatch")
