# Cameras
1. `cam = bpy.data.cameras.new('Cam'); o = bpy.data.objects.new('Cam', cam); scene.collection.objects.link(o); scene.camera = o`.
2. Lens 50 mm natural, 85 mm portrait/product, 24–35 mm wide; sensor 36 mm.
3. Aim: Track To constraint on an Empty at the subject, or set rotation_euler.
4. Depth of field: `cam.dof.use_dof = True; cam.dof.focus_object = target; cam.dof.aperture_fstop = 2.8`.
5. Frame check: render at 25% and look; keep the subject within the thirds.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
