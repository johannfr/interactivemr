from dataclasses import dataclass


@dataclass
class DiffItem:
    """Class for storing a diff-item and its metadata"""

    diff_data: str
    approved: bool
