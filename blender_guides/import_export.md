# Import / export
1. 4.x built-ins: `bpy.ops.wm.obj_import(filepath=..)` / `wm.obj_export`, `wm.stl_import` (4.1+), `wm.ply_import`, `wm.usd_import/export`, `wm.alembic_*`.
2. FBX: `bpy.ops.import_scene.fbx(filepath=..)`, `bpy.ops.export_scene.fbx(filepath=.., use_selection=True, apply_scale_options='FBX_SCALE_ALL', bake_anim=True)`.
3. glTF for web/games: `bpy.ops.export_scene.gltf(filepath=.., export_format='GLB')`.
4. Before export: apply transforms, check scale (Unity/Unreal), triangulate if the target needs it, pack/relink textures (`bpy.ops.file.pack_all()`).
5. After import: check scale, normals, materials and missing textures (`bpy.ops.file.find_missing_files`).

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
