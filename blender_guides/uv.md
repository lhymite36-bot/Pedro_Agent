# UV unwrapping
1. Mark seams in hidden places: select edges, `bpy.ops.mesh.mark_seam()`.
2. Unwrap: `bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.02)`; quick hard-surface: `bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)`.
3. Pack: `bpy.ops.uv.pack_islands(margin=0.01)`; average scale: `bpy.ops.uv.average_islands_scale()`.
4. Check stretching with a checker texture (UV Grid image on the material) – squares must be square and same size.
5. Multiple UV maps: `me.uv_layers.new(name='Lightmap')`; the active render map is used by default.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
