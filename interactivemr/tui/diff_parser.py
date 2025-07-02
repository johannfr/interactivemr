from dataclasses import dataclass, field
from re import sub


@dataclass
class DiffHunk:
    """Represents a single 'hunk' of changes in a diff."""

    header: str
    lines: list[tuple[str, str]] = field(default_factory=list)


def prepare_string_for_comparison(text_string: str) -> str:
    """
    Prepares a string for comparison by:
    1. Converting to lowercase.
    2. Removing common programming language specific noise (e.g., semicolons, curly braces, parentheses).
    3. Removing all punctuation.
    4. Normalizing whitespace (replacing multiple spaces with a single space, stripping leading/trailing).

    Args:
        text_string: The input string (e.g., a line of code).

    Returns:
        A cleaned string suitable for comparison.
    """
    cleaned_string = text_string.lower()
    cleaned_string = sub(r"[;(){}\[\].,:=+\-*\/%&|^!~<>]", " ", cleaned_string)
    cleaned_string = sub(r"[^a-z0-9\s]", "", cleaned_string)
    cleaned_string = sub(r"\s+", " ", cleaned_string).strip()

    return cleaned_string


def parse_diff_to_hunks(diff_text: str) -> list[DiffHunk]:
    """Parses a raw diff string into a list of DiffHunk objects."""
    hunks = []
    current_hunk = None
    lines = diff_text.split("\n")

    for line in lines:
        if line.startswith("@@"):
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = DiffHunk(header=line)
        elif current_hunk and (
            line.startswith("-") or line.startswith("+") or line.startswith(" ")
        ):
            current_hunk.lines.append((line[0], line[1:]))

    if current_hunk:
        hunks.append(current_hunk)

    return hunks
