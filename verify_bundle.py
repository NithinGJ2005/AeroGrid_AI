import zipfile
import hashlib
import re

BUNDLE_PATH = "aerogrid_colab_bundle.zip"

sha256 = hashlib.sha256(open(BUNDLE_PATH, "rb").read()).hexdigest()
print(f"Bundle SHA-256: {sha256}")

SENSITIVE_PATTERNS = [
    re.compile(rb"BEGIN\s+(RSA|OPENSSH|EC|DSA|PRIVATE)\s+KEY"),
    re.compile(rb"ghp_[A-Za-z0-9_]{36}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"SQLite format 3"),
]

with zipfile.ZipFile(BUNDLE_PATH, "r") as z:
    file_list = z.namelist()
    print(f"Total files in bundle: {len(file_list)}")
    print("\nComplete File Inventory:")
    for f in sorted(file_list):
        info = z.getinfo(f)
        print(f"  - {f} ({info.file_size} bytes)")
        
    print("\nContent Security Scan:")
    violations = []
    for f in file_list:
        content = z.read(f)
        for p in SENSITIVE_PATTERNS:
            if p.search(content):
                violations.append((f, p.pattern))
        if f.endswith(('.sqlite3', '.env', '.log', '.key', '.pem')):
            violations.append((f, "Forbidden filename extension"))
            
    if violations:
        print("[FAIL] Violations found in bundle:")
        for v in violations:
            print(f"  - {v}")
    else:
        print("[PASS] Zero sensitive filenames or secret signatures detected!")
