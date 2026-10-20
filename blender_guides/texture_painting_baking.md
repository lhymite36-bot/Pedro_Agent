# Texture painting and baking
1. Paint: create image (`bpy.data.images.new('BaseColor', 2048, 2048)`), add Image Texture node, set it active, mode TEXTURE_PAINT.
2. Baking needs Cycles: `scene.render.engine = 'CYCLES'`.
3. For each bake: select the target image node as ACTIVE node in the low-poly material (`nodes.active = tex`).
4. Normal from high to low: select high, then low active; `bpy.ops.object.bake(type='NORMAL', use_selected_to_active=True, cage_extrusion=0.02)`.
5. Other types: 'DIFFUSE' (pass_filter={'COLOR'}), 'ROUGHNESS', 'AO', 'EMIT', 'COMBINED'.
6. Save: `img.filepath_raw = path; img.file_format = 'PNG'; img.save()`. Margin 16 px against seams.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
