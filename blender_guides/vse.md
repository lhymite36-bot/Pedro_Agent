# Video Sequence Editor
1. `seq = scene.sequence_editor_create()`; add: `seq.sequences.new_movie('Clip', path, channel=1, frame_start=1)`, `new_sound`, `new_image` (4.4+: `strips` instead of `sequences`).
2. Cut: set frame_final_start/end or split with `bpy.ops.sequencer.split`.
3. Transitions: `seq.sequences.new_effect('Fade','CROSS',channel=3,frame_start=..,frame_end=..,seq1=a,seq2=b)`.
4. Text: effect type 'TEXT'.
5. Output FFMPEG H.264 + AAC; frame range to the edit length.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
