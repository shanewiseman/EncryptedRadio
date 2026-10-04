#!/usr/bin/env python3
"""Check repository text hygiene and local Markdown file links without dependencies.

Checks tracked and nonignored untracked text files. Link checks cover inline links
and reference definitions outside code; remote URLs and heading anchors are ignored.
This is a lightweight repository check, not a full Markdown parser or application test.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".bash", ".cfg", ".css", ".csv", ".html", ".ini", ".js", ".json",
    ".jsx", ".md", ".mjs", ".py", ".rst", ".sh", ".svg", ".toml",
    ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {".editorconfig", ".gitattributes", ".gitignore", "CODEOWNERS", "LICENSE", "Makefile"}
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"(`+).*?\1")
DESTINATION = r"(<[^>\n]+>|(?:\\.|[^\s()<>]|\([^()\n]*\))+)"
INLINE_LINK = re.compile(
    r"!?\[[^\]\n]*\]\(\s*" + DESTINATION
    + r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^()\n]*\)))?\s*\)"
)
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*" + DESTINATION, re.MULTILINE)


def repository_files(root: Path) -> list[Path]:
    """Use Git's ignore rules rather than walking caches or local secret files."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return sorted({root / name.decode("utf-8") for name in result.stdout.split(b"\0") if name})


def prose_lines(text: str):
    """Yield original line numbers and prose, omitting fenced and inline code."""
    fence_character = ""
    fence_length = 0
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line)
        if fence_character:
            if (
                match
                and match[1][0] == fence_character
                and len(match[1]) >= fence_length
                and not line[match.end():].strip()
            ):
                fence_character = ""
            continue
        if match:
            fence_character, fence_length = match[1][0], len(match[1])
            continue
        yield number, INLINE_CODE.sub("", line)


def markdown_errors(path: Path, text: str, root: Path) -> list[str]:
    errors = []
    for number, line in prose_lines(text):
        matches = list(INLINE_LINK.finditer(line)) + list(REFERENCE_LINK.finditer(line))
        for match in matches:
            destination = match[1].removeprefix("<").removesuffix(">")
            destination = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~])", r"\1", destination)
            try:
                parsed = urlsplit(destination)
            except ValueError:
                errors.append(f"{path.relative_to(root)}:{number}: malformed link {destination!r}")
                continue
            if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
                continue
            target = (path.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to(root) or not target.exists():
                errors.append(f"{path.relative_to(root)}:{number}: missing local link {destination!r}")
    return errors


def check_file(path: Path, root: Path) -> list[str]:
    label = path.relative_to(root)
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return [f"{label}: cannot read UTF-8 text: {error}"]
    errors = []
    if text.startswith("\ufeff"):
        errors.append(f"{label}: remove the UTF-8 byte order mark")
    if "\r" in text:
        errors.append(f"{label}: use LF line endings")
    if text and not text.endswith("\n"):
        errors.append(f"{label}: missing final newline")
    for number, line in enumerate(text.splitlines(), 1):
        if line.rstrip(" \t") != line:
            errors.append(f"{label}:{number}: trailing whitespace")
    if path.suffix.lower() == ".json":
        try:
            json.loads(text)
        except ValueError as error:
            errors.append(f"{label}: invalid JSON: {error}")
    if path.suffix.lower() == ".md":
        errors.extend(markdown_errors(path, text, root))
    return errors


def main() -> int:
    if sys.version_info < (3, 12):
        print("Python 3.12 or later is required.", file=sys.stderr)
        return 1
    try:
        files = repository_files(ROOT)
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as error:
        print(f"Cannot list repository files: {error}", file=sys.stderr)
        return 1
    errors = []
    checked = 0
    for path in files:
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_NAMES:
            continue
        checked += 1
        errors.extend(check_file(path, ROOT))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"Repository checks failed: {len(errors)} issue(s).", file=sys.stderr)
        return 1
    print(f"Repository hygiene passed ({checked} text files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
