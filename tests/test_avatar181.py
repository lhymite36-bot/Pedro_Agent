import json, struct, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "app_static" / "avatar3d"


def glb_json(p):
    b = p.read_bytes(); n = struct.unpack("<I", b[12:16])[0]
    return json.loads(b[20:20 + n])


class Avatar181(unittest.TestCase):
    def test_models_rigged_with_visemes(self):
        for name in ("male.glb", "mpfb.glb"):
            j = glb_json(ROOT / "th" / "models" / name)
            nodes = {n.get("name") for n in j["nodes"]}
            for bone in ("Hips", "Head", "LeftEye", "RightHand", "LeftToeBase"):
                self.assertIn(bone, nodes, name)
            targets = set()
            for m in j["meshes"]:
                targets |= set((m.get("extras") or {}).get("targetNames") or [])
            for t in ("viseme_aa", "viseme_PP", "eyeBlinkLeft", "mouthSmileLeft", "browInnerUp"):
                self.assertIn(t, targets, name)

    def test_page_wiring(self):
        js = (ROOT / "human.js").read_text(encoding="utf-8")
        self.assertIn("male.glb", js); self.assertIn("mpfb.glb", js)
        self.assertIn("Puck", js); self.assertIn("Sulafat", js)
        for a in ("Wave", "ThumbsUp", "Yes", "No", "Punch", "Sitting", "Standing", "Death", "Jump", "Dance", "Walking", "Running"):
            self.assertIn("'" + a + "'", js)
        self.assertNotIn("avatarsdk", js)
        self.assertIn("/avatar3d/human.html", (ROOT.parent / "batch180.js").read_text(encoding="utf-8"))

    def test_no_noncommercial_models_shipped(self):
        names = {p.name for p in (ROOT / "th" / "models").iterdir()}
        self.assertEqual(names, {"male.glb", "mpfb.glb"})


if __name__ == "__main__":
    unittest.main()
