
import marshal
import pickle
from textual.style import Style
from textual.color import Color
from rich.style import Style as RichStyle

def fixed_from_rich_style(cls, rich_style: RichStyle, theme = None) -> Style:
    """
    Patched from_rich_style to handle marshal-encoded _meta from Rich.
    Textual expects pickle, but Rich uses marshal.
    """
    _meta = rich_style._meta
    if _meta:
        # Check if it's valid pickle
        try:
            pickle.loads(_meta)
        except Exception:
            # Not valid pickle, try marshal
            try:
                data = marshal.loads(_meta)
                # It was marshal, so re-encode as pickle
                _meta = pickle.dumps(data)
            except Exception:
                # Neither? Keep as is or warn?
                pass

    return Style(
        (
            None
            if rich_style.bgcolor is None
            else Color.from_rich_color(rich_style.bgcolor, theme)
        ),
        (
            None
            if rich_style.color is None
            else Color.from_rich_color(rich_style.color, theme)
        ),
        bold=rich_style.bold,
        dim=rich_style.dim,
        italic=rich_style.italic,
        underline=rich_style.underline,
        underline2=rich_style.underline2,
        reverse=rich_style.reverse,
        strike=rich_style.strike,
        blink=rich_style.blink,
        link=rich_style.link,
        _meta=_meta,
    )

def apply_patch():
    # Only apply if not already applied (though simple reassignment is safe)
    if Style.from_rich_style.__func__ != fixed_from_rich_style:
        Style.from_rich_style = classmethod(fixed_from_rich_style)
