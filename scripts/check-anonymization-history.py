#!/usr/bin/env python3
"""Check all reachable Git revisions using the ignored local policy."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

SPEC = importlib.util.spec_from_file_location("repository_anonymization", Path(__file__).with_name("check-anonymization.py"))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def objects(root, identifiers):
    raw = CHECK.git(root, "cat-file", "--batch", input=b"\n".join(identifiers) + b"\n")
    offset = 0
    for identifier in identifiers:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        size = int(header[2])
        yield identifier.decode(), header[1].decode(), raw[end + 1:end + 1 + size]
        offset = end + size + 2


def check_history(root):
    rules, approved = CHECK.load_policy(root)
    identifiers = list(dict.fromkeys(CHECK.git(root, "rev-list", "--objects", "--all", "--no-object-names").splitlines()))
    failures, blobs, commits = [], 0, 0
    for identifier, kind, data in objects(root, identifiers):
        if kind == "blob":
            blobs += 1
            matches = CHECK.inspect("historical-content.json", data, rules, approved)
            if matches:
                failures.append({"scope": "historical_content", "object": identifier, "rules": matches})
        elif kind in ("commit", "tag"):
            message = data.split(b"\n\n", 1)[-1]
            metadata = b"\n".join(line for line in data.split(b"\n\n", 1)[0].splitlines()
                                  if line.startswith((b"author ", b"committer ", b"tagger ")))
            matches = CHECK.inspect("historical-message.txt", message + b"\n" + metadata, rules, approved)
            if matches:
                failures.append({"scope": "historical_metadata", "object": identifier, "rules": matches})
            if kind == "commit":
                commits += 1
                names = CHECK.git(root, "ls-tree", "-r", "--name-only", "-z", identifier).decode("utf-8").split("\0")
                for name in filter(None, names):
                    matches = CHECK.inspect(name, b"", rules, approved)
                    if matches:
                        failures.append({"scope": "historical_path", "object": identifier, "rules": matches})
    return {"valid": not failures, "scope": "reachable_history", "commits_checked": commits,
            "blobs_checked": blobs, "violations": failures}


def main():
    try:
        result = check_history(Path(__file__).resolve().parent.parent)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        print(json.dumps({"valid": False, "error": "Historical anonymization check failed; inspect local configuration."}))
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
