import bpy, sys, os, importlib.util
D = "/workspace/mpfb/data"
mpfb = None
for n, m in sys.modules.items():
    if n.endswith(".mpfb") and hasattr(m, "services"):
        mpfb = m
import bl_ext.user_default.mpfb as mpfb
from bl_ext.user_default.mpfb.services.humanservice import HumanService
from bl_ext.user_default.mpfb.services.assetservice import AssetService
spec = importlib.util.spec_from_file_location("thaddon", "/workspace/thmpfb/talkinghead-addon.py")
th = importlib.util.module_from_spec(spec); spec.loader.exec_module(th)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
macro = {"gender": 1.0, "age": 0.5, "muscle": 0.62, "weight": 0.5, "proportions": 0.6, "height": 0.55,
         "cupsize": 0.5, "firmness": 0.5, "race": {"african": 1.0, "asian": 0.0, "caucasian": 0.0}}
bm = HumanService.create_human(macro_detail_dict=macro)
AssetService.invalidate_custom_rig_cache()
print("RIGS", AssetService.get_custom_rigs())
rig = HumanService.add_custom_rig(bm, "custom.talkinghead")
MT = "GAMEENGINE"
HumanService.set_character_skin(f"{D}/skins/young_african_male/young_african_male.mhmat", bm, skin_type=MT, material_instances=False)
assets = [("eyes/high-poly/high-poly.mhclo", "Eyes"), ("eyebrows/eyebrow001/eyebrow001.mhclo", "Eyebrows"),
          ("eyelashes/eyelashes01/eyelashes01.mhclo", "Eyelashes"), ("teeth/teeth_base/teeth_base.mhclo", "Teeth"),
          ("tongue/tongue01/tongue01.mhclo", "Tongue"), ("hair/short01/short01.mhclo", "Hair"),
          ("clothes/male_casualsuit03/male_casualsuit03.mhclo", "Clothes"), ("clothes/shoes05/shoes05.mhclo", "Clothes")]
for rel, kind in assets:
    p = f"{D}/{rel}"
    if not os.path.isfile(p):
        import glob; c = glob.glob(os.path.dirname(p) + "/*.mhclo"); p = c[0] if c else p
    try:
        HumanService.add_mhclo_asset(p, bm, asset_type=kind, subdiv_levels=0, material_type=MT)
        print("ADDED", rel)
    except Exception as e:
        print("FAIL", rel, e)
from bl_ext.user_default.mpfb.services.targetservice import TargetService
TargetService.bake_targets(bm)
print("BASEMESH SK after bake", len(bm.data.shape_keys.key_blocks) if bm.data.shape_keys else 0)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print("MESHES", [o.name for o in meshes])
th.build_targets(mpfb, [o for o in meshes if any(k in o.name.lower() for k in ("human", "body", "eye", "teeth", "tongue", "lash", "brow")) or o is bm], "/workspace/thmpfb/talkinghead-targets.zip")
# apply delete/hide-helpers modifiers keeping shape keys
for o in meshes:
    names = th.find_modifier_names(o, ["delete", "hide helpers"])
    if names:
        bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
        th.apply_modifiers(bpy.context, names)
for o in meshes:   # drop subdiv etc. that glTF can't keep
    for m in list(o.modifiers):
        if m.type not in ("ARMATURE",):
            o.modifiers.remove(m)
for mat in bpy.data.materials:
    if mat.use_nodes:
        for nd in mat.node_tree.nodes:
            if nd.type == "TEX_IMAGE" and nd.image and "_eye" in nd.image.filepath and "brown" not in nd.image.filepath:
                print("EYE", nd.image.filepath); nd.image = bpy.data.images.load(D + "/eyes/materials/brown_eye.png")
rig.name = rig.data.name = "Armature"
bpy.ops.object.select_all(action="DESELECT"); rig.select_set(True); bpy.context.view_layer.objects.active = rig
th.scale_character([rig])
th.fix_bone_axes([rig], th.BONE_AXES_DATA_A)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in meshes:
    print("SK", o.name, len(o.data.shape_keys.key_blocks) if o.data.shape_keys else 0)
bpy.ops.wm.save_as_mainfile(filepath="/workspace/mbuild/male.blend")
bpy.ops.export_scene.gltf(filepath="/workspace/mbuild/male.glb", export_format="GLB", use_selection=True, export_animations=False,
                          export_morph=True, export_skins=True, export_yup=True)
print("DONE")
