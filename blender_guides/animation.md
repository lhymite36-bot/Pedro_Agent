# Animation
1. Keyframes: `obj.location = (0,0,0); obj.keyframe_insert('location', frame=1)`; again at another frame.
2. Frame range: scene.frame_start / frame_end; fps scene.render.fps.
3. Interpolation: `for fc in obj.animation_data.action.fcurves: for k in fc.keyframe_points: k.interpolation = 'BEZIER'` (4.4+ uses layered actions – use blender_docs_search 'fcurves channelbag' if fcurves is missing).
4. Cycles: add a 'CYCLES' F-modifier for loops.
5. Principles: anticipation, ease in/out, overlap, arcs. Preview with a viewport/OpenGL render or low-res render.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
