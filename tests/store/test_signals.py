from prospector.store.db import connect
from prospector.store.signals import LeadSignalsRepo


def test_set_and_read_bids(tmp_path):
    repo = LeadSignalsRepo(connect(tmp_path / "db.sqlite"))
    assert repo.bids(1) is None
    repo.set_bids(1, 12)
    repo.set_bids(1, 30)
    assert repo.bids(1) == 30
