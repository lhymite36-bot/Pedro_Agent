"""Write Config.java from the installed Ped Bot .env. Prints lengths only."""
from pathlib import Path

ENV = Path.home() / "AppData/Local/PedroAgent/.env"
OUT = Path(__file__).resolve().parent / "src/com/pedro/agent/Config.java"


def parse_env(text: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals


def java_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    if not ENV.is_file():
        raise SystemExit("missing Ped Bot .env")
    vals = parse_env(ENV.read_text(encoding="utf-8"))
    url = (vals.get("SUPABASE_URL") or "").strip().rstrip("/")
    anon = (vals.get("SUPABASE_ANON_KEY") or "").strip()
    if not url.startswith("https://") or not anon:
        raise SystemExit("SUPABASE_URL / SUPABASE_ANON_KEY missing")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "package com.pedro.agent;\n\n"
        "final class Config {\n"
        f"  static final String SUPABASE_URL = {java_string(url)};\n"
        f"  static final String ANON_KEY = {java_string(anon)};\n"
        "  private Config() {}\n"
        "}\n",
        encoding="utf-8",
    )
    print(f"wrote Config.java url_len={len(url)} anon_len={len(anon)}")


if __name__ == "__main__":
    main()
