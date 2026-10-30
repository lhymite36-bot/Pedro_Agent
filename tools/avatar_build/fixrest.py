"""Copy the TalkingHead reference rig's rest rotations (mpfb.glb) onto male.glb and recompute inverse bind matrices.
The mesh stays exactly where it is at rest; TalkingHead's pose templates then rotate the male like its reference rig."""
import json, struct, sys, numpy as np
src, ref, dst = sys.argv[1:4]
def load(f):
    b = open(f, 'rb').read(); jl = struct.unpack('<I', b[12:16])[0]
    j = json.loads(b[20:20 + jl]); bo = 20 + jl
    bl = struct.unpack('<I', b[bo:bo + 4])[0]; bin_ = bytearray(b[bo + 8:bo + 8 + bl]); return j, bin_
def q2m(q):
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
def local(n):
    M = np.eye(4); s = n.get('scale', [1, 1, 1])
    M[:3, :3] = q2m(n.get('rotation', [0, 0, 0, 1])) * np.array(s); M[:3, 3] = n.get('translation', [0, 0, 0]); return M
j, bin_ = load(src); rj, _ = load(ref)
rn = {n.get('name'): n for n in rj['nodes']}
parent = {}
for i, n in enumerate(j['nodes']):
    for c in n.get('children', []): parent[c] = i
skin = j['skins'][0]; joints = skin['joints']
# world matrices before
def world(i, cache):
    if i in cache: return cache[i]
    M = local(j['nodes'][i]); p = parent.get(i)
    W = world(p, cache) @ M if p is not None else M
    cache[i] = W; return W
old = {}; [world(i, old) for i in joints]
changed = 0
for i in joints:
    n = j['nodes'][i]; r = rn.get(n.get('name'))
    if r and 'rotation' in r:
        n['rotation'] = r['rotation']; changed += 1
# keep each joint's world *position* unchanged: re-solve translations top-down
new = {}
order = sorted(joints, key=lambda i: len([1 for _ in iter(lambda: None, 0)]) if False else 0)
def depth(i):
    d = 0
    while i in parent: i = parent[i]; d += 1
    return d
for i in sorted(joints, key=depth):
    p = parent.get(i)
    PW = (new[p] if p in new else world(p, {})) if p is not None else np.eye(4)
    if p is not None and p not in new: PW = old.get(p, PW)
    target = old[i][:3, 3]
    lt = np.linalg.inv(PW) @ np.append(target, 1)
    j['nodes'][i]['translation'] = [float(v) for v in lt[:3]]
    new[i] = PW @ local(j['nodes'][i])
acc = j['accessors'][skin['inverseBindMatrices']]; bv = j['bufferViews'][acc['bufferView']]
off = bv.get('byteOffset', 0) + acc.get('byteOffset', 0)
ibm = np.frombuffer(bytes(bin_[off:off + 64 * len(joints)]), dtype='<f4').reshape(-1, 4, 4)
# glTF IBMs are column-major; old world @ oldIBM gives each joint's bind offset. Keep it: newIBM = inv(newW) @ oldW @ oldIBM
out = []
for k, i in enumerate(joints):
    oI = ibm[k].T
    nI = np.linalg.inv(new[i]) @ old[i] @ oI
    out.append(nI.T.astype('<f4'))
bin_[off:off + 64 * len(joints)] = np.stack(out).tobytes()
js = json.dumps(j, separators=(',', ':')).encode(); js += b' ' * ((4 - len(js) % 4) % 4)
while len(bin_) % 4: bin_.append(0)
total = 12 + 8 + len(js) + 8 + len(bin_)
with open(dst, 'wb') as f:
    f.write(b'glTF' + struct.pack('<II', 2, total) + struct.pack('<I', len(js)) + b'JSON' + js + struct.pack('<I', len(bin_)) + b'BIN\x00' + bin_)
print('rest rotations copied for', changed, 'of', len(joints), 'joints')
