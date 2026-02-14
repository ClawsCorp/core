"""On-chain indexers that write append-only observed_* events to the DB.

These tools are meant to reduce dependence on the Oracle for data that can be
observed directly from the chain. They are optional and must be safe to run
repeatedly (idempotent inserts + cursors).
"""

