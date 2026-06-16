from services.chat.base_dispatcher import BaseRunDispatcher
from services.chat.hybrid_dispatcher import HybridDispatcher
from services.chat.run_dispatcher import RunDispatcher


def test_both_dispatchers_share_base_mark_failed():
    assert RunDispatcher._mark_failed is BaseRunDispatcher._mark_failed
    assert HybridDispatcher._mark_failed is BaseRunDispatcher._mark_failed
