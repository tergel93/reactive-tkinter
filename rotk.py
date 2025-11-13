import tkinter as tk
from tkinter import ttk
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    Literal,
    Union,
)
from enum import Enum, auto
from dataclasses import dataclass
import weakref


# ----------------- Observable -----------------


class Observable:
    def __init__(self, value: Any) -> None:
        self._value = value
        self._subscribers: list[Callable[[Any], None]] = []

    @property
    def value(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        if value == self._value:
            return
        self._value = value
        for subscriber in list(self._subscribers):
            subscriber(value)

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe


Action = Dict[str, Any]
Reducer = Callable[[Dict[str, Any], Action], Dict[str, Any]]
Listener = Callable[[], None]


# ----------------- Store (Redux-like) -----------------


class Store:
    def __init__(
        self,
        reducer: Reducer,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._reducer = reducer
        self._state: Dict[str, Any] = initial_state or {}
        self._listeners: List[Listener] = []

    def get_state(self) -> Dict[str, Any]:
        return self._state

    def dispatch(self, action: Action) -> None:
        next_state = self._reducer(self._state, action)
        self._state = next_state
        for listener in list(self._listeners):
            listener()

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return unsubscribe


_CURRENT_STORE: Optional[Store] = None


def configure_store(store: Store) -> None:
    global _CURRENT_STORE
    _CURRENT_STORE = store


def get_store() -> Store:
    if _CURRENT_STORE is None:
        raise RuntimeError("Store not configured")
    return _CURRENT_STORE


# ----------------- TkRegistry -----------------


class TkRegistry:
    def __init__(self) -> None:
        self._widgets: dict[str, weakref.ref[tk.Misc]] = {}

    def register(self, id: str, widget: tk.Misc) -> None:
        self._widgets[id] = weakref.ref(widget)

    def unregister(self, id: str, widget: Optional[tk.Misc] = None) -> None:
        ref = self._widgets.get(id)
        if ref is None:
            return
        if widget is not None:
            current = ref()
            if current is not widget:
                return
        self._widgets.pop(id, None)

    def get(self, id: str) -> Optional[tk.Misc]:
        ref = self._widgets.get(id)
        return ref() if ref is not None else None

    def __getitem__(self, id: str) -> tk.Misc:
        w = self.get(id)
        if w is None:
            raise KeyError(f"No widget registered for id={id!r}")
        return w

    def all_ids(self) -> List[str]:
        return list(self._widgets.keys())


# ----------------- Component base -----------------


class Component:
    def __init__(self, id: str, name: Optional[str] = None) -> None:
        if not id:
            raise ValueError("'id' is missing")
        self.id = id
        self.name = name

        self.parent: Optional[tk.Misc] = None
        self.root: Optional[tk.Misc] = None
        self._dom: Optional[TkRegistry] = None

        self._subscriptions: list[Callable[[], None]] = []
        self._disposed: bool = False

    def create_widget(self, parent: tk.Misc) -> tk.Misc:
        raise NotImplementedError

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True

        for unsub in self._subscriptions:
            unsub()
        self._subscriptions.clear()

        if hasattr(self, "_hook_slots"):
            self._hook_slots.clear()

    def mount(self, parent: tk.Misc) -> tk.Misc:
        if self.root is not None:
            raise RuntimeError("Component already mounted")

        self.parent = parent
        widget = self.create_widget(parent)
        self.root = widget

        if self.name:
            owner = getattr(parent, "_owner", parent)
            setattr(owner, self.name, self)

        toplevel = parent.winfo_toplevel()
        dom = getattr(toplevel, "dom", None)
        if isinstance(dom, TkRegistry):
            self._dom = dom
            dom.register(self.id, widget)

        def _on_destroy(event, comp=self, root=widget, dom=dom):
            if event.widget is root:
                if isinstance(dom, TkRegistry):
                    dom.unregister(comp.id, root)
                comp.dispose()

        widget.bind("<Destroy>", _on_destroy, add="+")
        return widget

    @property
    def widget(self) -> tk.Misc:
        if self.root is None:
            raise RuntimeError("Component not mounted yet")
        return self.root

    def on_state_changed(self) -> None:
        # Subclasses (like Row/Column) can override this
        pass

    def _track_subscription(self, unsubscribe: Callable[[], None]) -> None:
        self._subscriptions.append(unsubscribe)

    # ---- React-like use_state ----
    def use_state(self, initial):
        if not hasattr(self, "_hook_slots"):
            self._hook_slots: list[Observable] = []
            self._hook_index: int = 0

        idx = self._hook_index
        self._hook_index += 1

        if idx >= len(self._hook_slots):
            self._hook_slots.append(Observable(initial))

        obs = self._hook_slots[idx]

        def setter(value):
            if self._disposed:
                return
            obs.set(value)
            self.on_state_changed()

        return obs, setter

    # ---- Redux-like helpers ----
    def use_dispatch(self) -> Callable[[Action], None]:
        store = get_store()
        return store.dispatch

    def use_store_selector(
        self,
        selector: Callable[[Dict[str, Any]], Any],
        equality: Callable[[Any, Any], bool] = lambda a, b: a == b,
    ) -> Observable:
        """
        React-Redux–like hook: returns an Observable whose value is
        selector(store.get_state()). Re-runs selector on store changes,
        and updates the Observable if the result changed.
        """
        store = get_store()
        initial = selector(store.get_state())
        obs, set_obs = self.use_state(initial)

        # Subscribe once per observable instance
        if not hasattr(obs, "_store_subscribed"):

            def _on_store_change():
                if self._disposed:
                    return
                new_value = selector(store.get_state())
                if equality(new_value, obs.value):
                    return
                set_obs(new_value)

            unsub = store.subscribe(_on_store_change)
            self._track_subscription(unsub)
            setattr(obs, "_store_subscribed", True)

        return obs


# ----------------- TkWidget leaf components -----------------


class TkWidget(Component):
    def __init__(
        self,
        id: str,
        widget_cls: type[tk.Widget],
        name: Optional[str] = None,
        **widget_kwargs: Any,
    ) -> None:
        super().__init__(id=id, name=name)
        self.widget_cls = widget_cls
        self.widget_kwargs = widget_kwargs

    def create_widget(self, parent: tk.Misc) -> tk.Widget:
        resolved_kwargs: dict[str, Any] = {}
        observable_fields: list[tuple[str, Observable]] = []

        for key, value in self.widget_kwargs.items():
            if isinstance(value, Observable):
                resolved_kwargs[key] = value.value
                observable_fields.append((key, value))
            else:
                resolved_kwargs[key] = value

        w = self.widget_cls(parent, **resolved_kwargs)
        w._owner = self

        for key, obs in observable_fields:

            def _update(new_value, attr=key, widget=w):
                try:
                    widget.configure(**{attr: new_value})
                except tk.TclError:
                    pass

            unsub = obs.subscribe(_update)
            self._track_subscription(unsub)

        return w

    def pack(self, **kw: Any) -> "TkWidget":
        self.widget.pack(**kw)
        return self

    def grid(self, **kw: Any) -> "TkWidget":
        self.widget.grid(**kw)
        return self

    def place(self, **kw: Any) -> "TkWidget":
        self.widget.place(**kw)
        return self


# ----------------- FrameComponent base -----------------


class FrameComponent(Component):
    DEBUG_BORDERS: bool = False

    _DEBUG_COLORS = [
        "#ff6666",
        "#66ccff",
        "#99cc66",
        "#ffcc66",
        "#cc99ff",
        "#ff99cc",
        "#66ffcc",
        "#cccccc",
    ]
    _DEBUG_COLOR_INDEX: int = 0

    @classmethod
    def enable_debug_borders(cls, enabled: bool = True) -> None:
        cls.DEBUG_BORDERS = enabled

    @classmethod
    def _next_debug_color(cls) -> str:
        color = cls._DEBUG_COLORS[cls._DEBUG_COLOR_INDEX % len(cls._DEBUG_COLORS)]
        cls._DEBUG_COLOR_INDEX += 1
        return color

    def __init__(
        self,
        id: str,
        name: Optional[str] = None,
        *,
        frame_kwargs: Optional[Dict[str, Any]] = None,
        debug_color: Optional[str] = None,
    ) -> None:
        super().__init__(id=id, name=name)
        self._frame_kwargs = frame_kwargs or {}
        self._debug_color = debug_color

    def build(self, frame: ttk.Frame) -> None:
        # subclasses override
        pass

    def create_widget(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(parent, **self._frame_kwargs)
        frame._owner = self

        # reset hook index before build (React-style)
        if hasattr(self, "_hook_slots"):
            self._hook_index = 0

        if self.DEBUG_BORDERS:
            color = self._debug_color or self._next_debug_color()

            frame.configure(borderwidth=1, relief="solid")

            try:
                frame.configure(
                    highlightthickness=1,
                    highlightbackground=color,
                    highlightcolor=color,
                )
            except tk.TclError:
                pass

            try:
                style = ttk.Style()
                style_name = f"DebugFrame.{id(self)}.TFrame"
                style.configure(style_name, background=color)
                frame.configure(style=style_name)
            except tk.TclError:
                pass

        spec = self.build(frame)

        if spec is not None:
            if isinstance(spec, tuple):
                child, opts = spec
                opts = dict(opts)
            else:
                child, opts = spec, {}

            if not isinstance(child, Component):
                raise TypeError

            sticky = opts.pop("sticky", "nsew")
            expand = opts.pop("expand", True)
            weight = opts.pop("weight", 1 if expand else 0)

            child_root = child.mount(frame)
            child_root.grid(row=0, column=0, sticky=sticky, **opts)

            if weight:
                frame.rowconfigure(0, weight=weight)
                frame.columnconfigure(0, weight=weight)

        return frame

    def pack(self, **kw: Any) -> "FrameComponent":
        self.widget.pack(**kw)
        return self

    def grid(self, **kw: Any) -> "FrameComponent":
        self.widget.grid(**kw)
        return self

    def place(self, **kw: Any) -> "FrameComponent":
        self.widget.place(**kw)
        return self


# ----------------- Floating -----------------


class Floating(FrameComponent):
    def __init__(
        self,
        id: str,
        child: Component,
        *,
        name: Optional[str] = None,
        frame_kwargs: Optional[Dict[str, Any]] = None,
        relx: float = 1.0,
        rely: float = 0.0,
        x: int = -8,
        y: int = 8,
        anchor: str = "ne",
        **extra_place_kw: Any,
    ) -> None:
        super().__init__(id=id, name=name, frame_kwargs=frame_kwargs)
        self._child = child
        self._place_kw: Dict[str, Any] = {
            "relx": relx,
            "rely": rely,
            "x": x,
            "y": y,
            "anchor": anchor,
        }
        self._place_kw.update(extra_place_kw)

    def build(self, root: ttk.Frame) -> None:
        w = self._child.mount(root)
        w.place(**self._place_kw)


# ----------------- Alignment / layouts -----------------


class HAlign(Enum):
    LEFT = auto()
    CENTER = auto()
    RIGHT = auto()
    STRETCH = auto()


class VAlign(Enum):
    TOP = auto()
    CENTER = auto()
    BOTTOM = auto()
    STRETCH = auto()


@dataclass
class RowLayout:
    expand: bool = False
    width: Optional[int] = None
    halign: Optional[HAlign] = None
    padx: Optional[int] = None
    pady: Optional[int] = None
    sticky: Optional[str] = None


@dataclass
class ColumnLayout:
    expand: bool = False
    height: Optional[int] = None
    valign: Optional[VAlign] = None
    halign: Optional[HAlign] = None
    padx: Optional[int] = None
    pady: Optional[int] = None
    sticky: Optional[str] = None


Child = Component
RowChildLayout = Union[Dict[str, Any], RowLayout]
ColumnChildLayout = Union[Dict[str, Any], ColumnLayout]
RowChildSpec = Union[Component, Tuple[Component, RowChildLayout]]
ColumnChildSpec = Union[Component, Tuple[Component, ColumnChildLayout]]


# ----------------- Row -----------------


class Row(FrameComponent):
    def __init__(
        self,
        id: str,
        children: Optional[Iterable[RowChildSpec]] = None,
        *,
        name: Optional[str] = None,
        gap_x: int = 6,
        gap_y: int = 4,
        frame_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(id=id, name=name, frame_kwargs=frame_kwargs)
        self._gap_x = gap_x
        self._gap_y = gap_y
        self._children_eager: List[RowChildSpec] = list(children) if children else []

        self._root_frame: Optional[ttk.Frame] = None
        self._mounted_children: Dict[str, Component] = {}
        self._child_widgets: Dict[str, tk.Misc] = {}
        self._order: List[str] = []

    def add(self, *cells: RowChildSpec) -> "Row":
        self._children_eager.extend(cells)
        return self

    def iter_children(self) -> Iterable[RowChildSpec]:
        return self._children_eager

    def _row_layout_to_opts(self, layout: RowLayout) -> Dict[str, Any]:
        opts: Dict[str, Any] = {}

        if layout.sticky is not None:
            opts["sticky"] = layout.sticky
        elif layout.halign is not None:
            if layout.halign is HAlign.LEFT:
                opts["sticky"] = "w"
            elif layout.halign is HAlign.CENTER:
                opts["sticky"] = ""
            elif layout.halign is HAlign.RIGHT:
                opts["sticky"] = "e"
            elif layout.halign is HAlign.STRETCH:
                opts["sticky"] = "we"

        if layout.padx is not None:
            opts["padx"] = layout.padx
        if layout.pady is not None:
            opts["pady"] = layout.pady

        if layout.expand:
            opts["expand"] = True
        if layout.width is not None:
            opts["width"] = layout.width

        return opts

    def build(self, root: ttk.Frame) -> None:
        self._root_frame = root
        self._refresh_children()

    def _refresh_children(self) -> None:
        root = self._root_frame
        if root is None:
            return

        new_specs = list(self.iter_children())
        new_ids: list[str] = []
        specs_by_id: dict[str, Tuple[Component, Optional[RowChildLayout]]] = {}

        for spec in new_specs:
            if isinstance(spec, tuple):
                child, layout = spec
            else:
                child, layout = spec, None

            if not isinstance(child, Component):
                raise TypeError

            cid = child.id
            new_ids.append(cid)
            specs_by_id[cid] = (child, layout)

        # Remove old children
        for cid in list(self._mounted_children.keys()):
            if cid not in new_ids:
                self._mounted_children.pop(cid, None)
                w = self._child_widgets.pop(cid, None)
                if w is not None:
                    try:
                        w.destroy()
                    except tk.TclError:
                        pass

        # Clear old grid
        for w in list(self._child_widgets.values()):
            try:
                w.grid_forget()
            except tk.TclError:
                pass

        # Reset column weights
        max_cols = max(len(self._order), len(new_ids)) + 4
        for col_idx in range(max_cols):
            try:
                root.columnconfigure(col_idx, weight=0, minsize=0)
            except tk.TclError:
                pass

        new_mounted: Dict[str, Component] = {}
        new_widgets: Dict[str, tk.Misc] = {}

        col = 0
        for cid in new_ids:
            child, layout = specs_by_id[cid]

            if isinstance(layout, RowLayout):
                opts = self._row_layout_to_opts(layout)
            elif isinstance(layout, dict) or layout is None:
                opts = dict(layout or {})
            else:
                raise TypeError

            sticky = opts.pop("sticky", "w")
            padx = opts.pop("padx", self._gap_x)
            pady = opts.pop("pady", self._gap_y)
            expand = opts.pop("expand", False)
            width = opts.pop("width", None)

            if cid in self._mounted_children and child is self._mounted_children[cid]:
                w = self._child_widgets[cid]
            else:
                if cid in self._mounted_children:
                    old_widget = self._child_widgets.get(cid)
                    if old_widget is not None:
                        try:
                            old_widget.destroy()
                        except tk.TclError:
                            pass
                w = child.mount(root)

            w.grid(
                row=0,
                column=col,
                sticky=sticky,
                padx=padx,
                pady=pady,
                **opts,
            )

            if width is not None:
                root.columnconfigure(col, minsize=width)
            if expand:
                root.columnconfigure(col, weight=1)

            new_mounted[cid] = child
            new_widgets[cid] = w
            col += 1

        self._mounted_children = new_mounted
        self._child_widgets = new_widgets
        self._order = new_ids

    def refresh(self) -> None:
        self._refresh_children()

    def on_state_changed(self) -> None:
        self.refresh()


# ----------------- Column -----------------


class Column(FrameComponent):
    def __init__(
        self,
        id: str,
        children: Optional[Iterable[ColumnChildSpec]] = None,
        *,
        name: Optional[str] = None,
        gap_x: int = 6,
        gap_y: int = 4,
        frame_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(id=id, name=name, frame_kwargs=frame_kwargs)
        self._gap_x = gap_x
        self._gap_y = gap_y
        self._children_eager: List[ColumnChildSpec] = list(children) if children else []

        self._root_frame: Optional[ttk.Frame] = None
        self._mounted_children: Dict[str, Component] = {}
        self._child_widgets: Dict[str, tk.Misc] = {}
        self._order: List[str] = []

    def add(self, *cells: ColumnChildSpec) -> "Column":
        self._children_eager.extend(cells)
        return self

    def iter_children(self) -> Iterable[ColumnChildSpec]:
        return self._children_eager

    def _column_layout_to_opts(self, layout: ColumnLayout) -> Dict[str, Any]:
        opts: Dict[str, Any] = {}

        sticky_set = False
        sticky_value = ""

        if layout.sticky is not None:
            sticky_value = layout.sticky
            sticky_set = True
        else:
            parts: list[str] = []
            alignment_specified = False

            if layout.valign is not None:
                alignment_specified = True
                if layout.valign is VAlign.TOP:
                    parts.append("n")
                elif layout.valign is VAlign.CENTER:
                    pass
                elif layout.valign is VAlign.BOTTOM:
                    parts.append("s")
                elif layout.valign is VAlign.STRETCH:
                    parts.extend(["n", "s"])

            if layout.halign is not None:
                alignment_specified = True
                if layout.halign is HAlign.LEFT:
                    parts.append("w")
                elif layout.halign is HAlign.CENTER:
                    pass
                elif layout.halign is HAlign.RIGHT:
                    parts.append("e")
                elif layout.halign is HAlign.STRETCH:
                    parts.extend(["w", "e"])

            if alignment_specified:
                ordered: list[str] = []
                for letter in parts:
                    if letter and letter not in ordered:
                        ordered.append(letter)
                sticky_value = "".join(ordered)
                sticky_set = True

        if sticky_set:
            opts["sticky"] = sticky_value

        if layout.padx is not None:
            opts["padx"] = layout.padx
        if layout.pady is not None:
            opts["pady"] = layout.pady

        if layout.expand:
            opts["expand"] = True
        if layout.height is not None:
            opts["height"] = layout.height

        return opts

    def build(self, root: ttk.Frame) -> None:
        self._root_frame = root
        self._refresh_children()

    def _refresh_children(self) -> None:
        root = self._root_frame
        if root is None:
            return

        new_specs = list(self.iter_children())
        new_ids: list[str] = []
        specs_by_id: dict[str, Tuple[Component, Optional[ColumnChildLayout]]] = {}

        for spec in new_specs:
            if isinstance(spec, tuple):
                child, layout = spec
            else:
                child, layout = spec, None

            if not isinstance(child, Component):
                raise TypeError

            cid = child.id
            new_ids.append(cid)
            specs_by_id[cid] = (child, layout)

        # Remove old children
        for cid in list(self._mounted_children.keys()):
            if cid not in new_ids:
                self._mounted_children.pop(cid, None)
                w = self._child_widgets.pop(cid, None)
                if w is not None:
                    try:
                        w.destroy()
                    except tk.TclError:
                        pass

        # Clear old grid
        for w in list(self._child_widgets.values()):
            try:
                w.grid_forget()
            except tk.TclError:
                pass

        # Reset row weights
        max_rows = max(len(self._order), len(new_ids)) + 4
        for row_idx in range(max_rows):
            try:
                root.rowconfigure(row_idx, weight=0, minsize=0)
            except tk.TclError:
                pass

        new_mounted: Dict[str, Component] = {}
        new_widgets: Dict[str, tk.Misc] = {}

        row = 0
        for cid in new_ids:
            child, layout = specs_by_id[cid]

            if isinstance(layout, ColumnLayout):
                opts = self._column_layout_to_opts(layout)
            elif isinstance(layout, dict) or layout is None:
                opts = dict(layout or {})
            else:
                raise TypeError

            sticky = opts.pop("sticky", "w")
            padx = opts.pop("padx", self._gap_x)
            pady = opts.pop("pady", self._gap_y)
            expand = opts.pop("expand", False)
            height = opts.pop("height", None)

            if cid in self._mounted_children and child is self._mounted_children[cid]:
                w = self._child_widgets[cid]
            else:
                if cid in self._mounted_children:
                    old_widget = self._child_widgets.get(cid)
                    if old_widget is not None:
                        try:
                            old_widget.destroy()
                        except tk.TclError:
                            pass
                w = child.mount(root)

            w.grid(
                row=row,
                column=0,
                sticky=sticky,
                padx=padx,
                pady=pady,
                **opts,
            )

            if height is not None:
                root.rowconfigure(row, minsize=height)
            if expand:
                root.rowconfigure(row, weight=1)

            new_mounted[cid] = child
            new_widgets[cid] = w
            row += 1

        self._mounted_children = new_mounted
        self._child_widgets = new_widgets
        self._order = new_ids

    def refresh(self) -> None:
        self._refresh_children()

    def on_state_changed(self) -> None:
        self.refresh()


# ----------------- Scrollable -----------------


class Scrollable(FrameComponent):
    def __init__(
        self,
        id: str,
        content: Component,
        *,
        name: Optional[str] = None,
        orient: Literal["vertical", "horizontal", "both"] = "vertical",
        frame_kwargs: Optional[Dict[str, Any]] = None,
        canvas_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(id=id, name=name, frame_kwargs=frame_kwargs)
        self._orient = orient
        self._canvas_kwargs = canvas_kwargs or {}
        self.content = content

        self.canvas: Optional[tk.Canvas] = None
        self.inner: Optional[ttk.Frame] = None

    def build(self, root: ttk.Frame) -> None:
        canvas = tk.Canvas(root, highlightthickness=0, **self._canvas_kwargs)
        canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas = canvas

        # Scrollbars
        if self._orient in ("vertical", "both"):
            vsb = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
            vsb.grid(row=0, column=1, sticky="ns")
            canvas.configure(yscrollcommand=vsb.set)

        if self._orient in ("horizontal", "both"):
            hsb = ttk.Scrollbar(root, orient="horizontal", command=canvas.xview)
            hsb.grid(row=1, column=0, sticky="we")
            canvas.configure(xscrollcommand=hsb.set)

        inner = ttk.Frame(canvas)
        inner._owner = self
        self.inner = inner

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        # Update scrollregion when inner changes size
        def _on_inner_configure(event):
            bbox = canvas.bbox("all")
            if bbox is not None:
                canvas.configure(scrollregion=bbox)

        inner.bind("<Configure>", _on_inner_configure)

        # For vertical-only scrollable, match width of canvas to inner
        if self._orient == "vertical":

            def _on_canvas_configure(event):
                try:
                    canvas.itemconfigure(window_id, width=event.width)
                except tk.TclError:
                    pass

            canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse wheel support (vertical scrolling)
        if self._orient in ("vertical", "both"):

            def _on_mousewheel(event):
                # Windows / macOS delta
                if event.delta:
                    canvas.yview_scroll(-int(event.delta / 120), "units")
                else:
                    # X11 (event.num 4/5)
                    if event.num == 4:
                        canvas.yview_scroll(-1, "units")
                    elif event.num == 5:
                        canvas.yview_scroll(1, "units")

            # Windows/macOS
            canvas.bind("<MouseWheel>", _on_mousewheel)
            # X11
            canvas.bind("<Button-4>", _on_mousewheel)
            canvas.bind("<Button-5>", _on_mousewheel)

        content_widget = self.content.mount(inner)
        content_widget.pack(fill="both", expand=True)


class ScrollableVertical(Scrollable):
    def __init__(
        self,
        id: str,
        content: Component,
        *,
        name: Optional[str] = None,
        frame_kwargs: Optional[Dict[str, Any]] = None,
        canvas_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            id=id,
            content=content,
            name=name,
            orient="vertical",
            frame_kwargs=frame_kwargs,
            canvas_kwargs=canvas_kwargs,
        )


class ScrollableHorizontal(Scrollable):
    def __init__(
        self,
        id: str,
        content: Component,
        *,
        name: Optional[str] = None,
        frame_kwargs: Optional[Dict[str, Any]] = None,
        canvas_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            id=id,
            content=content,
            name=name,
            orient="horizontal",
            frame_kwargs=frame_kwargs,
            canvas_kwargs=canvas_kwargs,
        )


class ScrollableBoth(Scrollable):
    def __init__(
        self,
        id: str,
        content: Component,
        *,
        name: Optional[str] = None,
        frame_kwargs: Optional[Dict[str, Any]] = None,
        canvas_kwargs: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            id=id,
            content=content,
            name=name,
            orient="both",
            frame_kwargs=frame_kwargs,
            canvas_kwargs=canvas_kwargs,
        )


# ----------------- MenuButton -----------------


class MenuButton(Component):
    def __init__(
        self,
        id: str,
        *,
        text: str,
        items: Sequence[tuple[str, Any]] | None = None,
        command: Callable[[str, Any], None] | None = None,
        name: Optional[str] = None,
        **kw: Any,
    ) -> None:
        super().__init__(id=id, name=name)
        self._text = text
        self._items = list(items or [])
        self._command = command
        self._btn_kwargs = kw

    def create_widget(self, parent: tk.Misc) -> ttk.Menubutton:
        btn = ttk.Menubutton(parent, text=self._text, **self._btn_kwargs)
        menu = tk.Menu(btn, tearoff=0)

        for label, payload in self._items:
            if self._command is None:
                if not callable(payload):
                    raise TypeError(f"Menu item payload for {label!r} must be callable")
                menu.add_command(label=label, command=payload)
            else:

                def _handler(lbl=label, value=payload):
                    self._command(lbl, value)

                menu.add_command(label=label, command=_handler)

        btn["menu"] = menu
        btn._owner = self
        return btn


# ----------------- Widget factories -----------------


def Label(id: str, **kw: Any) -> TkWidget:
    return TkWidget(id=id, widget_cls=ttk.Label, **kw)


def Entry(id: str, **kw: Any) -> TkWidget:
    return TkWidget(id=id, widget_cls=ttk.Entry, **kw)


def Button(id: str, **kw: Any) -> TkWidget:
    return TkWidget(id=id, widget_cls=ttk.Button, **kw)


def Combobox(id: str, **kw: Any) -> TkWidget:
    return TkWidget(id=id, widget_cls=ttk.Combobox, **kw)


def Text(id: str, **kw: Any) -> TkWidget:
    return TkWidget(id=id, widget_cls=tk.Text, **kw)


# ----------------- Window / root -----------------


class Window(tk.Tk):
    def __init__(
        self,
        *,
        title: str = "Application",
        width: int = 800,
        height: int = 600,
        content: Optional[Component] = None,
        **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.title(title)

        self.dom = TkRegistry()

        root_frame = ttk.Frame(self)
        root_frame.pack(fill="both", expand=True)
        self._root_frame = root_frame

        self._main = ttk.Frame(root_frame)
        self._main.pack(fill="both", expand=True)

        self._overlay = ttk.Frame(root_frame)
        self._overlay.pack(fill="both", expand=True)
        self._overlay.lower(self._main)

        self._content: Optional[Component] = None

        if content is not None:
            self.set_content(content)

        self.after_idle(lambda: self.geometry(f"{width}x{height}"))

    def set_content(self, content: Component):
        for child in self._main.winfo_children():
            child.destroy()

        widget = content.mount(self._main)
        widget.pack(fill="both", expand=True)
        self._content = content
        return content

    def portal(self, component: Component, **place_kw: Any) -> Component:
        self._overlay.lift()

        widget = component.mount(self._overlay)
        if not place_kw:
            place_kw = dict(relx=0.5, rely=0.5, anchor="center")
        widget.place(**place_kw)
        return component

    def clear_portal(self) -> None:
        for child in self._overlay.winfo_children():
            child.destroy()
        self._overlay.lower(self._main)
