# Rigging
1. Armature: `bpy.ops.object.armature_add()`; edit mode, extrude bones (`edit_bones.new`, head/tail, parent, use_connect).
2. Name bones with .L/.R and use symmetrize (`bpy.ops.armature.symmetrize()`).
3. Bind: select mesh then armature, `bpy.ops.object.parent_set(type='ARMATURE_AUTO')` (automatic weights); fix in Weight Paint.
4. IK: pose bone constraint 'IK' with target and pole, chain_count 2 for limbs.
5. Rigify for humans: enable add-on, add meta-rig, fit bones, Generate Rig.
6. Test by posing extremes; check deformation at elbows/knees.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
