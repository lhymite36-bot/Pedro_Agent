# Modelling (hard-surface and organic)
1. Start from the right primitive: `bpy.ops.mesh.primitive_cube_add(size=2, location=(0,0,0))`; name it at once (`obj.name = 'Body'`).
2. Keep scale applied before modifiers: `bpy.ops.object.transform_apply(scale=True)`.
3. Non-destructive stack, in order: Mirror (`obj.modifiers.new('Mirror','MIRROR')`, use_clip=True) → Bevel (width 0.02, segments 3, limit_method 'ANGLE') → Subdivision Surface (levels 2, render_levels 3) → Weighted Normal (keep_sharp=True; needs shade smooth + auto smooth / 'Smooth by Angle' in 4.1+).
4. Edit with bmesh for precision: `bm = bmesh.new(); bm.from_mesh(me)`; extrude with `bmesh.ops.extrude_face_region`, inset with `bmesh.ops.inset_region`, then `bm.to_mesh(me); bm.free()`.
5. Support loops / creases to hold edges under subdivision; check for n-gons on curved areas.
6. Booleans: `mod = obj.modifiers.new('Cut','BOOLEAN'); mod.object = cutter; mod.solver='EXACT'`; hide the cutter (`display_type='WIRE'`, hide_render=True).
7. Clean up: merge by distance (`bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)`), recalc normals (`bmesh.ops.recalc_face_normals`).
8. Real-world scale: 1 unit = 1 m.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
