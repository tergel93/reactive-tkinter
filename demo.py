from rotk import *
from demo_reducer import reducer, INITIAL_STATE
from demo_header import TodoHeader
from demo_content import TodoContent

if __name__ == "__main__":
    configure_store(
        Store(
            reducer,
            initial_state=INITIAL_STATE,
        )
    )

    content = TodoContent(id="todo_content")
    header = TodoHeader(
        id="todo_header",
        on_add_task=content.add_task,
        on_clear_done=content.clear_done,
        on_filter_change=content.set_filter,
    )

    window = Window(
        title="Tk Todo",
        width=900,
        height=600,
        content=Column(
            id="root",
            children=[
                (
                    header,
                    ColumnLayout(
                        expand=False,
                        valign=VAlign.TOP,
                        halign=HAlign.STRETCH,
                    ),
                ),
                (
                    content,
                    ColumnLayout(
                        expand=True,
                        valign=VAlign.STRETCH,
                        halign=HAlign.STRETCH,
                    ),
                ),
            ],
        ),
    )

    def debug_print_dom():
        print("DOM ids:", window.dom.all_ids())

    window.after(1000, debug_print_dom)
    window.mainloop()
