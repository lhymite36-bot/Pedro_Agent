# Geometry nodes
1. `mod = obj.modifiers.new('GN','NODES'); tree = bpy.data.node_groups.new('Scatter','GeometryNodeTree'); mod.node_group = tree`.
2. 4.x: interface sockets: `tree.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')` (and OUTPUT); add 'NodeGroupInput'/'NodeGroupOutput' nodes.
3. Scatter: Distribute Points on Faces → Instance on Points (instance from Object Info / Collection Info) → Realize Instances if needed → Join Geometry with original.
4. Randomise: Random Value into rotation/scale.
5. Expose parameters as group inputs; set via `mod['Socket_2'] = value` (check identifiers with `[s.identifier for s in tree.interface.items_tree]`).

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
