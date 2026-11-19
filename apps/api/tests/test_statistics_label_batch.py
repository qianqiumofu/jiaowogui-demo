from sqlalchemy import event
import pytest

from app.core.db import get_engine
from app.modules.directory import service as directory
from app.modules.statistics import service as statistics


def test_statistics_batches_labels_and_restores_context(seeded_demo_db):
    engine = get_engine()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, 'before_cursor_execute', record)
    try:
        with engine.connect() as conn:
            statistics.query(conn, date_from='2026-11-01', date_to='2026-11-14')
        label_queries = [s for s in statements if 'SELECT school_id,display_name FROM students' in s]
        assert not label_queries
        batch_queries = [s for s in statements if 'SELECT student_id,school_id,display_name FROM students' in s]
        assert len(batch_queries) == 1
        assert directory._label_snapshot.get() is None
    finally:
        event.remove(engine, 'before_cursor_execute', record)


def test_label_snapshot_is_released_after_failure(seeded_demo_db):
    with get_engine().connect() as conn:
        with pytest.raises(RuntimeError):
            with directory.prefetched_labels(conn):
                assert directory._label_snapshot.get()
                raise RuntimeError('synthetic query failure')
        assert directory._label_snapshot.get() is None
