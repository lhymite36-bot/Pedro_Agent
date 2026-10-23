# Physics
1. Rigid body: `bpy.ops.rigidbody.object_add(type='ACTIVE')`, ground PASSIVE; mass, friction, collision shape (CONVEX_HULL / MESH).
2. Cloth: modifier 'CLOTH' with quality 5–10; colliders get 'COLLISION'. Pin group via vertex group.
3. Fluid (Mantaflow): domain + flow + effector; bake with `bpy.ops.fluid.bake_all()` – slow; set resolution low for previews.
4. Particles/hair: particle system type EMITTER/HAIR; 4.x hair curves use geometry nodes.
5. Always bake caches before rendering (`bpy.ops.ptcache.bake_all(bake=True)`).

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
