import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph

class Checkpointer:
    _saver = None
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def init_checkpointer(self)-> SqliteSaver :
        conn = sqlite3.connect(database=self.db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn=conn)
        return checkpointer
    
    def get_checkpointer(self):
        if self._saver is None:
            self.init_checkpointer()
        return self._saver
    
    def load_thread_checkpointer(self, builder: CompiledStateGraph, thread_id: str):
        config = {"configurable":{"thread_id": thread_id}}

        return builder.get_state(config)

        