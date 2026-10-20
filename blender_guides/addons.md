# Add-ons and extensions
1. 4.2+: extensions platform (extensions.blender.org); built-ins like Rigify, Node Wrangler are add-ons you enable: `bpy.ops.preferences.addon_enable(module='rigify')` (4.2+: module names may be 'bl_ext.blender_org.<name>' for extensions).
2. Save preferences: `bpy.ops.wm.save_userpref()`.
3. Only enable add-ons the user asked for; never download add-ons from unknown sites.
4. Useful: Node Wrangler (Ctrl+Shift+T principled setup), Rigify, Bool Tool, LoopTools.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
