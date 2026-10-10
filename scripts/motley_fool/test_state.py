import state

ROW = {"symbol": "AAA", "action": "Buy", "rec_date": "09/01/2026"}


def test_same_pick_twice_is_added_once():
    first = state.ingest_scraped_rows([ROW])
    second = state.ingest_scraped_rows([ROW, {**ROW}])
    assert len(first) == 1 and second == []
    assert list(state.load_state()["picks"]) == ["AAA"]


def test_baseline_seed_records_without_queueing():
    queued = state.ingest_scraped_rows([ROW, {**ROW, "symbol": "BBB"}], seed_baseline=True)
    assert queued == []
    st = state.load_state()
    assert {p["status"] for p in st["picks"].values()} == {"baseline"}
    assert state.list_pending() == []


def test_after_baseline_only_new_picks_queue():
    state.ingest_scraped_rows([ROW], seed_baseline=True)
    queued = state.ingest_scraped_rows([ROW, {**ROW, "symbol": "NEW"}])
    assert [p["symbol"] for p in queued] == ["NEW"]
    assert [p["symbol"] for p in state.list_pending()] == ["NEW"]
