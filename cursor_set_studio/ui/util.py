"""Small UI helpers."""
from __future__ import annotations

from PySide6.QtWidgets import QLayout


def clear_layout(layout: QLayout, keep_trailing: int = 0) -> None:
    """Remove and destroy every widget in `layout`.

    `deleteLater()` alone is not enough: it defers destruction to the event
    loop, so the old widgets keep painting while replacements are inserted and
    the rows visibly stack on top of each other. Re-parenting to None detaches
    them from the visual tree immediately; deleteLater then frees them safely.

    `keep_trailing` leaves that many items at the end alone, which is how the
    trailing stretch survives a rebuild.
    """
    while layout.count() > keep_trailing:
        item = layout.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                clear_layout(child)
                child.deleteLater()
