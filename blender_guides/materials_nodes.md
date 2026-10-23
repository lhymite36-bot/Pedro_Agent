# Materials and shader nodes
1. `mat = bpy.data.materials.new('Paint'); mat.use_nodes = True; bsdf = mat.node_tree.nodes['Principled BSDF']`.
2. Inputs (4.x names): 'Base Color', 'Metallic', 'Roughness', 'IOR', 'Alpha', 'Normal', 'Emission Color', 'Emission Strength', 'Coat Weight', 'Subsurface Weight', 'Transmission Weight'. Check names with blender_docs_search if a KeyError appears (3.x used 'Emission', 'Subsurface', 'Transmission').
3. Image texture: `tex = nodes.new('ShaderNodeTexImage'); tex.image = bpy.data.images.load(path)`; link `links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])`. Non-colour maps (roughness, normal) need `tex.image.colorspace_settings.name = 'Non-Color'`.
4. Normal maps go through 'ShaderNodeNormalMap'. Procedural: Noise / Voronoi / Musgrave(→Noise in 4.1) + ColorRamp.
5. Assign: `obj.data.materials.append(mat)`; per-face: material_index on polygons.
6. Physically plausible values: metals Metallic 1 with coloured base; dielectrics Metallic 0, roughness 0.2–0.8.

## Verify
After each stage: list the scene (objects, modifiers, materials, counts) from bpy, render a small preview (`scene.render.resolution_percentage = 25`, `bpy.ops.render.render(write_still=True)`) and look at it. On a traceback: read the last line, look the call up with blender_docs_search, fix, rerun only the failing part.
