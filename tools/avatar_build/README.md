# Male avatar build (CC0, free)

Rebuilds `app_static/avatar3d/th/models/male.glb` from MakeHuman/MPFB CC0 assets with the
TalkingHead rig (Mixamo-compatible), ARKit face units and Oculus visemes.

1. Blender 5.x + MPFB 2 extension; MakeHuman system assets, visemes02, faceunits01 asset packs.
2. TalkingHead `blender/MPFB` files (addon, talkinghead.mpfbskel, talkinghead.mhw, talkinghead-targets.zip).
3. Copy the rig to `<mpfb user data>/rigs/talkinghead.json` (+ `"identifying_bones": ["LeftToe_End"]`)
   and the weights to `rigs/weights.talkinghead.json`.
4. Shirt texture: male_casualsuit03 recoloured to green/cream plaid; eyes recoloured brown (see notes in build_male.py).
5. `blender -b --python build_male.py` → male.glb
6. `python3 fixrest.py male.glb mpfb.glb male_fixed.glb` copies the reference rig's rest rotations so TalkingHead poses fit.
7. `gltf-transform resize --width 2048 --height 2048` then `gltf-transform webp --quality 88`.

Paths inside build_male.py point at the build box; adjust them on another machine.
