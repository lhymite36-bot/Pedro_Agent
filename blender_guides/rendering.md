# Rendering
1. Engine: 'BLENDER_EEVEE_NEXT' (4.2+) / 'BLENDER_EEVEE' (older) for speed, 'CYCLES' for quality. Check enum with blender_docs_search if set fails.
2. Cycles: `scene.cycles.samples = 128`, `scene.cycles.use_denoising = True`; GPU: Preferences > System (cycles device 'OPTIX'/'CUDA'/'HIP') then `scene.cycles.device = 'GPU'`.
3. Output: `scene.render.resolution_x/y`, `resolution_percentage`, `filepath`, `image_settings.file_format = 'PNG'`.
4. Still: `bpy.ops.render.render(write_still=True)`; animation: `bpy.ops.render.render(animation=True)` with FFMPEG container MPEG4/H264.
5. Preview fast first (25%, low samples), then final.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
