import os
import zipfile
import re
from pathlib import Path

ROOT_DIR = Path(".").resolve()
BUNDLE_PATH = ROOT_DIR / "aerogrid_colab_bundle.zip"

ALLOWLIST_PATTERNS = [
    # Top-level dependency / config
    "pyproject.toml",
    "README.md",
]

# Walk rules for directories
INCLUDE_DIRS = {
    "app": [".py", ".html", ".js", ".css", ".png", ".svg"],
    "sample_docs": [".md", ".json"],
    "scripts": [".py"],
}

EXCLUDE_FILENAMES = {
    "run_vllm_gateway.py",  # Exclude gateway to avoid local confusion
    "auth.sqlite3",
    "sample_db.sqlite3",
    ".env",
}

EXCLUDE_PATTERNS = [
    re.compile(r".*\.sqlite3.*", re.IGNORECASE),
    re.compile(r".*\.log$", re.IGNORECASE),
    re.compile(r".*\.env.*", re.IGNORECASE),
    re.compile(r".*__pycache__.*", re.IGNORECASE),
    re.compile(r".*\.pyc$", re.IGNORECASE),
    re.compile(r".*\.pem$", re.IGNORECASE),
    re.compile(r".*\.key$", re.IGNORECASE),
    re.compile(r".*\.cert$", re.IGNORECASE),
    re.compile(r".*\.crt$", re.IGNORECASE),
]

def should_include(rel_path: str) -> bool:
    rel_path_posix = rel_path.replace("\\", "/")
    basename = os.path.basename(rel_path_posix)
    
    # Check explicit exclusions
    if basename in EXCLUDE_FILENAMES:
        return False
    for pat in EXCLUDE_PATTERNS:
        if pat.match(rel_path_posix):
            return False
            
    # Top-level allowlist
    if rel_path_posix in ALLOWLIST_PATTERNS:
        return True
        
    # Check dir inclusions
    parts = rel_path_posix.split("/")
    top_dir = parts[0]
    if top_dir in INCLUDE_DIRS:
        # Check specific scripts allowlist
        if top_dir == "scripts":
            if basename in ["benchmark_e2e_workload.py", "benchmark_capacity.py"]:
                return True
            return False
        # Extension check
        ext = os.path.splitext(basename)[1].lower()
        if ext in INCLUDE_DIRS[top_dir]:
            return True
            
    return False

files_to_pack = []
for root, dirs, files in os.walk(ROOT_DIR):
    for f in files:
        full_path = Path(root) / f
        rel_path = full_path.relative_to(ROOT_DIR).as_posix()
        if should_include(rel_path):
            files_to_pack.append((full_path, rel_path))

files_to_pack.sort(key=lambda x: x[1])

print(f"Building sanitized bundle with {len(files_to_pack)} files...")
with zipfile.ZipFile(BUNDLE_PATH, "w", compression=zipfile.ZIP_DEFLATED) as z:
    for full_path, rel_path in files_to_pack:
        z.write(full_path, arcname=rel_path)

print(f"Bundle created at {BUNDLE_PATH} (size: {BUNDLE_PATH.stat().st_size} bytes)")
