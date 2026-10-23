# Grease Pencil
1. Add: `bpy.ops.object.gpencil_add(type='STROKE')` (4.2) / grease pencil v3 in 4.3+ (`bpy.ops.object.grease_pencil_add`). Check version with blender_docs_search.
2. Layers per element (lines, fill, shadows); materials with stroke/fill.
3. Draw in Draw mode; modifiers: Smooth, Thickness, Noise; Line Art for outlines from 3D scenes.
4. Animate with keyframes per frame (2s or 3s for hand-drawn feel).

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
