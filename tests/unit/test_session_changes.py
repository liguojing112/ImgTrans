from src.domain.session import SessionChanges


def test_session_tracks_single_and_partial_batch_exports_independently() -> None:
    changes = SessionChanges()
    changes.mark_single_changed()
    changes.replace_batch_results({"one", "two"})
    assert changes.has_unexported_changes
    assert "2 张" in changes.warning_summary()
    changes.mark_single_exported()
    changes.mark_batch_exported({"one"})
    assert changes.pending_batch_items == {"two"}
    changes.mark_batch_exported({"two"})
    assert not changes.has_unexported_changes


def test_replacing_or_clearing_batch_results_does_not_change_single_state() -> None:
    changes = SessionChanges(single_image_dirty=True)
    changes.replace_batch_results({"old"})
    changes.replace_batch_results({"new"})
    assert changes.pending_batch_items == {"new"}
    changes.clear_batch()
    assert changes.single_image_dirty
