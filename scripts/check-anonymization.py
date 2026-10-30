#!/usr/bin/env python3
"""Check repository paths and content without disclosing private matches."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote

POLICY_NAME = "ANONYMIZATION.local.json"


def git(root, *args, input=None):
    return subprocess.check_output(["git", *args], cwd=root, input=input)


def load_policy(root):
    path = root / POLICY_NAME
    if not path.is_file():
        raise ValueError("Private policy is missing; provision it outside Git.")
    if git(root, "ls-files", "-z", "--", POLICY_NAME):
        raise ValueError("Private policy must never be tracked.")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", POLICY_NAME], cwd=root, check=False
    )
    if ignored.returncode:
        raise ValueError("Private policy must be covered by .gitignore.")
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("version") != 1 or not policy.get("rules"):
        raise ValueError("Private policy is incomplete.")
    rules = []
    for item in policy["rules"]:
        rule_id = item["id"]
        if not re.fullmatch(r"R[0-9]+", rule_id):
            raise ValueError("Rule identifiers must be anonymous.")
        rules.append((rule_id, re.compile(item["pattern"], re.IGNORECASE)))
    return rules, set(policy.get("approved_binary_sha256", []))


def index_files(root):
    entries = []
    for record in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, digest, stage = header.split()
        if stage != b"0":
            raise ValueError("Resolve unmerged index entries before checking.")
        if mode in (b"120000", b"160000"):
            raise ValueError("Links and submodules require a separate content review.")
        entries.append((path.decode("utf-8"), digest))
    digests = list(dict.fromkeys(digest for _, digest in entries))
    raw = git(root, "cat-file", "--batch", input=b"\n".join(digests) + b"\n")
    blobs, offset = {}, 0
    for digest in digests:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise ValueError("Unable to read staged content.")
        size = int(header[2])
        blobs[digest] = raw[end + 1:end + 1 + size]
        offset = end + size + 2
    return [(path, blobs[digest]) for path, digest in entries]


def working_files(root):
    names = git(root, "ls-files", "-co", "--exclude-standard", "-z").split(b"\0")
    result = []
    for raw in sorted(set(names)):
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = root / name
        if path.is_symlink():
            raise ValueError("Links require a separate content review.")
        if path.is_file():
            result.append((name, path.read_bytes()))
    return result


def inspect(name, data, rules, approved):
    violations = {rule_id for rule_id, regex in rules if regex.search(name)}
    try:
        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = data.decode(encoding)
        if "\0" in text:
            raise UnicodeError()
    except UnicodeError:
        if hashlib.sha256(data).hexdigest() not in approved:
            violations.add("BINARY_REVIEW_REQUIRED")
        return sorted(violations)
    texts = [text, unquote(text)]
    if name.lower().endswith(".json"):
        try:
            texts.append(json.dumps(json.loads(text), ensure_ascii=False))
        except json.JSONDecodeError:
            # Deliberately invalid JSON fixtures still need escape-aware scanning.
            texts.append(re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text))
    for rule_id, regex in rules:
        if any(regex.search(value) for value in texts):
            violations.add(rule_id)
    return sorted(violations)


def run(root, staged=False):
    rules, approved = load_policy(root)
    records = index_files(root) if staged else working_files(root)
    failures = []
    for name, data in records:
        matched = inspect(name, data, rules, approved)
        if matched:
            safe_name = name
            for _, regex in rules:
                safe_name = regex.sub("[redacted]", safe_name)
            failures.append({"path": safe_name, "rules": matched})
    return {
        "valid": not failures,
        "scope": "index" if staged else "working_tree",
        "files_checked": len(records),
        "violations": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Check the complete Git index.")
    args = parser.parse_args()
    try:
        result = run(Path(__file__).resolve().parent.parent, args.staged)
    except (ValueError, KeyError, TypeError, OSError, re.error, subprocess.SubprocessError):
        print(json.dumps({"valid": False, "error": "Anonymization policy or repository check failed; inspect local configuration."}))
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
