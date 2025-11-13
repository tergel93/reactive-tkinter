from typing import Any, Dict

import tkinter as tk
from tkinter import ttk

from rotk import (
    FrameComponent,
    Column,
    Row,
    RowLayout,
    HAlign,
    ScrollableVertical,
    Label,
    Button,
    Window,
    get_store,
)


TaskEntry = tuple[int, str, bool]


def _select_tasks(state: Dict[str, Any]) -> tuple[TaskEntry, ...]:
    entries: list[TaskEntry] = []
    for raw in state.get("tasks", []):
        entries.append(
            (
                int(raw.get("id", 0)),
                str(raw.get("text", "")),
                bool(raw.get("done", False)),
            )
        )
    return tuple(entries)


class TodoContent(FrameComponent):
    def __init__(self, id: str = "todo_content") -> None:
        super().__init__(id=id, name="content")

        self._filter_mode: str = "all"

        self.tasks_column = Column("tasks_column")

        self._dispatch = None  # type: ignore[assignment]
        self._tasks_source = None  # type: ignore[assignment]

    # ------------ internal helpers ------------

    def _current_tasks(self) -> tuple[TaskEntry, ...]:
        if self._tasks_source is None:
            return tuple()
        return self._tasks_source.value

    def _iter_filtered_tasks(self, tasks: tuple[TaskEntry, ...]) -> list[TaskEntry]:
        if self._filter_mode == "open":
            return [t for t in tasks if not t[2]]
        if self._filter_mode == "done":
            return [t for t in tasks if t[2]]
        return list(tasks)

    def _rebuild_task_children(self):
        children = []
        all_tasks = self._current_tasks()
        filtered = self._iter_filtered_tasks(all_tasks)

        if not filtered:
            msg = (
                "No tasks yet. Add one above!"
                if not all_tasks
                else "No tasks match this filter."
            )
            children.append(Label("tasks_empty_placeholder", text=msg))
        else:
            for tid, text, done in filtered:
                prefix = "✓" if done else " "

                label = Label(f"task_label_{tid}", text=f"[{prefix}] {text}")

                toggle_btn = Button(
                    f"task_toggle_{tid}",
                    text="Undo" if done else "Done",
                    width=6,
                    command=lambda task_id=tid: self.toggle_task_done(task_id),
                )

                delete_btn = Button(
                    f"task_delete_{tid}",
                    text="✕",
                    width=3,
                    command=lambda task_id=tid: self.delete_task(task_id),
                )

                row = Row(
                    f"task_row_{tid}",
                    children=[
                        (label, RowLayout(expand=True, halign=HAlign.STRETCH)),
                        toggle_btn,
                        delete_btn,
                    ],
                )
                children.append(row)

        self.tasks_column._children_eager = children

    def _refresh_task_view(self) -> None:
        self._rebuild_task_children()
        self.tasks_column.refresh()

    def _ensure_dispatch(self):
        if self._dispatch is None:
            self._dispatch = self.use_dispatch()
        return self._dispatch

    # ------------ actions ------------

    def add_task(self) -> None:
        if self.root is None:
            return
        dispatch = self._ensure_dispatch()

        toplevel: Window = self.root.winfo_toplevel()  # type: ignore[assignment]
        entry_widget: tk.Entry = toplevel.dom["task_input"]  # type: ignore[assignment]

        text = entry_widget.get().strip()
        if not text:
            dispatch({"type": "SET_STATUS", "payload": "Cannot add empty task"})
            return

        entry_widget.delete(0, tk.END)

        next_id = int(get_store().get_state().get("next_task_id", 1))
        dispatch({"type": "ADD_TASK", "payload": text})
        dispatch(
            {
                "type": "SET_STATUS",
                "payload": f"Added task #{next_id}",
            }
        )

    def delete_task(self, task_id: int) -> None:
        dispatch = self._ensure_dispatch()

        tasks_before = self._current_tasks()
        if not any(tid == task_id for tid, _, _ in tasks_before):
            return

        dispatch({"type": "DELETE_TASK", "payload": task_id})

        dispatch(
            {
                "type": "SET_STATUS",
                "payload": f"Deleted task #{task_id}",
            }
        )

    def toggle_task_done(self, task_id: int) -> None:
        dispatch = self._ensure_dispatch()

        tasks_before = self._current_tasks()
        target = next((t for t in tasks_before if t[0] == task_id), None)
        if target is None:
            return

        _, _, was_done = target

        dispatch({"type": "TOGGLE_TASK_DONE", "payload": task_id})

        dispatch(
            {
                "type": "SET_STATUS",
                "payload": f"Marked task #{task_id} as {'done' if not was_done else 'open'}",
            }
        )

    def clear_done(self) -> None:
        dispatch = self._ensure_dispatch()

        done_before = sum(1 for _, _, done in self._current_tasks() if done)
        if done_before == 0:
            return

        dispatch({"type": "CLEAR_DONE_TASKS"})
        dispatch(
            {
                "type": "SET_STATUS",
                "payload": f"Cleared {done_before} completed task(s)",
            }
        )

    def set_filter(self, label: str, value: str) -> None:
        dispatch = self._ensure_dispatch()

        self._filter_mode = value
        self._refresh_task_view()
        dispatch(
            {
                "type": "SET_STATUS",
                "payload": f"Filter set to: {label}",
            }
        )

    # ------------ build (render) ------------

    def build(self, frame: ttk.Frame) -> None:
        # store dispatch for internal use
        self._dispatch = self.use_dispatch()
        self._tasks_source = self.use_store_selector(_select_tasks)
        self._refresh_task_view()

        if self._tasks_source is not None:
            unsub = self._tasks_source.subscribe(
                lambda _value: self._refresh_task_view()
            )
            self._track_subscription(unsub)

        return ScrollableVertical(
            "tasks_scroll",
            content=self.tasks_column,
        )
