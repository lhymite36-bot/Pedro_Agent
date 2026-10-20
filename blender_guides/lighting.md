# Lighting
1. Three-point: key (Area, 1000 W at ~45° side/above), fill (opposite, 30–50% power), rim (behind, strong, narrow).
   `light = bpy.data.lights.new('Key','AREA'); light.energy = 1000; light.size = 2; o = bpy.data.objects.new('Key', light); scene.collection.objects.link(o)`.
2. Point at subject with a Track To constraint (track_axis 'TRACK_NEGATIVE_Z', up 'UP_Y').
3. Environment: world nodes Background + Environment Texture (HDRI) for realism; strength 0.5–1.5.
4. Sun for exterior (energy 3–5, angle 0.5° crisp shadows).
5. Eevee: enable shadows/raytracing as needed; Cycles: light paths & clamp to reduce fireflies.
6. Exposure under Color Management; view transform 'AgX' (4.x) or 'Filmic'.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
