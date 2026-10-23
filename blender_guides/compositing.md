# Compositing
1. `scene.use_nodes = True; tree = scene.node_tree` (4.x; 5.x uses compositing node groups – check docs).
2. Render Layers → Glare (Fog Glow) → Color Balance / Curves → Lens Distortion (slight dispersion) → Composite + Viewer.
3. Denoise node with Normal/Albedo passes (enable view_layer.cycles.denoising_store_passes).
4. Passes for control: AO, Mist, Cryptomatte for masks.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
