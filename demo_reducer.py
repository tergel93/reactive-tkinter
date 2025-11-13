from typing import Any, Dict, List

from rotk import Action


def _derive_task_metadata(tasks: List[Dict[str, Any]]) -> tuple[str, bool]:
    open_count = sum(1 for t in tasks if not t.get("done"))
    done_count = sum(1 for t in tasks if t.get("done"))
    summary = f"{open_count} open / {done_count} done"
    return summary, done_count > 0


def _assign_tasks(state: Dict[str, Any], tasks: List[Dict[str, Any]]) -> None:
    summary, clear_enabled = _derive_task_metadata(tasks)
    state["tasks"] = tasks
    state["summary"] = summary
    state["clear_enabled"] = clear_enabled


def reducer(state: Dict[str, Any], action: Action) -> Dict[str, Any]:
    state = dict(state)  # shallow copy

    t = action.get("type")

    if t == "SET_STATUS":
        state["status"] = action.get("payload", "")
    elif t == "SET_SUMMARY":
        state["summary"] = action.get("payload", "")
    elif t == "SET_CLEAR_ENABLED":
        state["clear_enabled"] = bool(action.get("payload", False))
    elif t == "ADD_TASK":
        text = (action.get("payload") or "").strip()
        if not text:
            return state

        next_id = int(state.get("next_task_id", 1))
        task = {"id": next_id, "text": text, "done": False}
        tasks = list(state.get("tasks", [])) + [task]
        state["next_task_id"] = next_id + 1

        _assign_tasks(state, tasks)
    elif t == "DELETE_TASK":
        task_id = action.get("payload")
        if task_id is None:
            return state

        tasks = list(state.get("tasks", []))
        new_tasks = [t for t in tasks if t.get("id") != task_id]
        if len(new_tasks) == len(tasks):
            return state

        _assign_tasks(state, new_tasks)
    elif t == "TOGGLE_TASK_DONE":
        task_id = action.get("payload")
        if task_id is None:
            return state

        tasks = list(state.get("tasks", []))
        changed = False
        new_tasks: List[Dict[str, Any]] = []

        for task in tasks:
            if task.get("id") == task_id:
                updated = dict(task)
                updated["done"] = not bool(task.get("done"))
                new_tasks.append(updated)
                changed = True
            else:
                new_tasks.append(task)

        if not changed:
            return state

        _assign_tasks(state, new_tasks)
    elif t == "CLEAR_DONE_TASKS":
        tasks = list(state.get("tasks", []))
        new_tasks = [t for t in tasks if not t.get("done")]

        if len(new_tasks) == len(tasks):
            return state

        _assign_tasks(state, new_tasks)

    return state


INITIAL_STATE: Dict[str, Any] = {
    "status": "Ready",
    "summary": "0 open / 0 done",
    "clear_enabled": False,
    "tasks": [],
    "next_task_id": 1,
}
