"""Checkpoint store: save/restore/list/prune (Stage 1, Milestone 2).

Mechanism only — *when* a checkpoint is taken is the agent loop's job (M3).
"""

import pytest

from src.checkpoints import CheckpointStore, CheckpointMetadata
from src.document_model import parse_docx
from tests.test_support import TEST_DOCX


def _model():
    return parse_docx(TEST_DOCX)


class TestSaveRestore:
    def test_restore_preserves_counts(self, temp_dir):
        store = CheckpointStore(temp_dir / "checkpoints")
        model = _model()
        checkpoint_id = store.save(model, label="baseline")

        restored = store.restore(checkpoint_id)
        assert restored.paragraph_count == model.paragraph_count
        assert restored.comment_count == model.comment_count
        assert restored.thread_count == model.thread_count
        assert restored.revision_count == model.revision_count

    def test_restore_after_edit_is_independent(self, temp_dir):
        store = CheckpointStore(temp_dir / "checkpoints")
        model = _model()
        before = model.comment_count
        checkpoint_id = store.save(model, label="before remove")

        thread_id = next(iter(model.comments.threads))
        model.remove_comment(thread_id)
        assert model.comment_count == before - 1

        restored = store.restore(checkpoint_id)
        assert restored.comment_count == before

    def test_restore_comment_object_identity(self, temp_dir):
        # Tier 1 item #2 guarantees thread.root is the same object as the entry
        # in comments[...] after a to_dict/from_dict round-trip.
        store = CheckpointStore(temp_dir / "checkpoints")
        checkpoint_id = store.save(_model())
        restored = store.restore(checkpoint_id)

        thread = next(iter(restored.comments.threads.values()))
        root_id = thread.root.comment_id
        assert restored.comments.comments[root_id] is thread.root

    def test_restore_unknown_raises(self, temp_dir):
        store = CheckpointStore(temp_dir / "checkpoints")
        with pytest.raises(KeyError):
            store.restore("does-not-exist")


class TestListAndPrune:
    def test_list_newest_first_with_metadata(self, temp_dir):
        store = CheckpointStore(temp_dir / "checkpoints")
        model = _model()
        ids = [store.save(model, label=f"step {i}") for i in range(3)]

        metas = store.list()
        assert [m.checkpoint_id for m in metas] == list(reversed(ids))
        assert all(isinstance(m, CheckpointMetadata) for m in metas)
        assert metas[0].label == "step 2"
        assert metas[0].sequence > metas[-1].sequence

    def test_fifo_prune_keeps_newest_max(self, temp_dir):
        store = CheckpointStore(temp_dir / "checkpoints", max_checkpoints=3)
        model = _model()
        ids = [store.save(model, label=f"s{i}") for i in range(6)]

        metas = store.list()
        assert len(metas) == 3
        kept = {m.checkpoint_id for m in metas}
        assert kept == set(ids[-3:])  # newest three survive
        # Oldest were pruned and can no longer be restored.
        with pytest.raises(KeyError):
            store.restore(ids[0])

    def test_creates_directory(self, temp_dir):
        target = temp_dir / "nested" / "checkpoints"
        CheckpointStore(target)
        assert target.is_dir()
