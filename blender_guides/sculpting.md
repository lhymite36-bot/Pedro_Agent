# Sculpting
1. Base mesh with even quads; add Multires (`obj.modifiers.new('Multires','MULTIRES')`, then `bpy.ops.object.multires_subdivide(modifier='Multires', mode='CATMULL_CLARK')` 3–5 times) or use Dyntopo / Voxel remesh (`obj.data.remesh_voxel_size = 0.02; bpy.ops.object.voxel_remesh()`) for blocking.
2. Sculpt mode: `bpy.ops.object.mode_set(mode='SCULPT')`. Brushes: Draw/Clay Strips for forms, Grab for silhouette, Crease for lines, Smooth (Shift) to relax, Inflate, Pinch.
3. Work big to small: silhouette → primary forms → secondary → details on higher levels.
4. Symmetry X on (`tool_settings.sculpt.use_symmetry_x`).
5. Masks and face sets to isolate areas.
6. For games: bake the high detail to a normal map on a retopologised low mesh (see baking).

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
