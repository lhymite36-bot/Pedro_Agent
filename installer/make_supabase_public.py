"""Write supabase_public.py (git-ignored) with the PUBLIC project URL + anon key
for the installer build. Source: SUPABASE_URL/SUPABASE_ANON_KEY env vars, else
android_app/src/com/pedro/agent/Config.java. Never writes the service role key.
Prints lengths only."""
import os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
url = os.environ.get("SUPABASE_URL", "").strip(); anon = os.environ.get("SUPABASE_ANON_KEY", "").strip()
cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "android_app/src/com/pedro/agent/Config.java"
if (not url or not anon) and cfg.is_file():
    t = cfg.read_text(encoding="utf-8")
    url = url or re.search(r'SUPABASE_URL\s*=\s*"([^"]+)"', t).group(1)
    anon = anon or re.search(r'ANON_KEY\s*=\s*"([^"]+)"', t).group(1)
if not url.startswith("https://") or not anon:
    raise SystemExit("public Supabase URL / anon key not found")
if '"role":"service_role"' in anon.replace(" ", ""):
    raise SystemExit("refusing: that is a service role key")
import base64, json
try:
    mid = anon.split(".")[1]; role = json.loads(base64.urlsafe_b64decode(mid + "=" * (-len(mid) % 4))).get("role")
except Exception:
    role = "anon"
if role == "service_role":
    raise SystemExit("refusing: that is a service role key")
(ROOT / "supabase_public.py").write_text(
    '"""Built-in PUBLIC Supabase project config (anon key is public by design). Generated at build time; .env overrides it."""\n'
    f"SUPABASE_URL = {url!r}\nSUPABASE_ANON_KEY = {anon!r}\n", encoding="utf-8")
print("ok url_len", len(url), "anon_len", len(anon), "role", role)
