from typing import Callable

from tkinter import ttk

from rotk import (
    FrameComponent,
    Column,
    ColumnLayout,
    Row,
    RowLayout,
    HAlign,
    MenuButton,
    Label,
    Entry,
    Button,
)


class TodoHeader(FrameComponent):
    def __init__(
        self,
        id: str = "todo_header",
        *,
        on_add_task: Callable[[], None],
        on_clear_done: Callable[[], None],
        on_filter_change: Callable[[str, str], None],
    ) -> None:
        super().__init__(id=id, name="header")
        self._on_add_task = on_add_task
        self._on_clear_done = on_clear_done
        self._on_filter_change = on_filter_change

        self._dispatch = None  # type: ignore[assignment]

    def build(self, frame: ttk.Frame) -> None:
        status = self.use_store_selector(lambda s: s.get("status", ""))
        summary = self.use_store_selector(lambda s: s.get("summary", ""))
        clear_state = self.use_store_selector(
            lambda s: "normal" if s.get("clear_enabled", False) else "disabled"
        )
        self._dispatch = self.use_dispatch()

        top_row = Row(
            "top_row",
            children=[
                MenuButton(
                    id="filter_menu",
                    text="Filter",
                    items=[
                        ("All", "all"),
                        ("Open", "open"),
                        ("Done", "done"),
                    ],
                    command=self._on_filter_change,
                ),
                (
                    Entry("task_input"),
                    RowLayout(expand=True, halign=HAlign.STRETCH),
                ),
                Button(
                    "add_button",
                    text="Add",
                    command=self._on_add_task,
                ),
                Button(
                    "clear_done_button",
                    text="Clear Done",
                    state=clear_state,
                    command=self._on_clear_done,
                ),
            ],
        )


        return Column(
            "header_column",
            children=[
                (
                    top_row,
                    ColumnLayout(expand=False)
                ),
                (
                    Row(
                        id="status_row",
                        children=[
                            (
                                Label("status_label", text=status),
                                RowLayout(expand=True, halign=HAlign.STRETCH)
                            ),
                            Label("summary_label", text=summary),
                        ]
                    ),
                    ColumnLayout(expand=False)
                ),
            ],
        )
