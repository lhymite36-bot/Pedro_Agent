# Retopology
1. Duplicate target or new plane; Shrinkwrap modifier to the high mesh (wrap_method 'PROJECT' or 'NEAREST_SURFACEPOINT'), on top of stack with Mirror below.
2. Snapping: `tool_settings.snap_elements = {'FACE_NEAREST'}` (4.x) / 'FACE_PROJECT', use_snap_project.
3. Quads only, edge loops follow deformation (eyes, mouth, joints get loops), poles at low curvature spots.
4. Quick option: Quad Remesher-free path = `voxel_remesh` then `bpy.ops.object.quadriflow_remesh(target_faces=5000)`.
5. Check: no triangles/n-gons (select by sides), even density, normals out.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
