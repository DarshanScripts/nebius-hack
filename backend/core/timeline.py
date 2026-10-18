"""Deterministic timeline construction; models never choose audio placements."""
from contracts.models import AudioBundle, DialogueScript, SceneSlot, TimedUtterance, Timeline
from contracts.validation import validate_audio, validate_timeline


def build_timeline(script: DialogueScript, audio: AudioBundle) -> Timeline:
    validate_audio(audio, script)
    clips = {u.dialogue_id: u for u in audio.utterances}
    cursor, utterances = 15, []
    for index, turn in enumerate(script.turns):
        end = cursor + clips[turn.dialogue_id].frame_count
        utterances.append(TimedUtterance(dialogue_id=turn.dialogue_id, start_frame=cursor, end_frame=end))
        cursor = end + (6 if index % 2 == 0 else 24)
    boundaries = [0] + [utterances[i].end_frame + 12 for i in (1, 3, 5, 7, 9)] + [1800]
    result = Timeline(
        project_id=script.project_id, script_revision=script.script_revision,
        utterances=utterances,
        scenes=[SceneSlot(scene_id=f"s{i+1:02}", index=i+1, start_frame=boundaries[i],
                          end_frame=boundaries[i+1],
                          dialogue_ids=[t.dialogue_id for t in script.turns[i*2:i*2+2]])
                for i in range(6)],
    )
    validate_timeline(result, script, audio)
    return result
