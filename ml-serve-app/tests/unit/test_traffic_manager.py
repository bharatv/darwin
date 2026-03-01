import pytest

from ml_serve_core.service.traffic_manager import TrafficManager


@pytest.mark.unit
class TestTrafficManagerHelpers:
    def test_select_count_for_weight(self):
        tm = TrafficManager()
        assert tm._select_count_for_weight(total=0, weight_percent=50) == 0
        assert tm._select_count_for_weight(total=10, weight_percent=0) == 0
        assert tm._select_count_for_weight(total=10, weight_percent=100) == 10
        assert tm._select_count_for_weight(total=10, weight_percent=50) in (5,)

    def test_deterministic_pick_is_stable(self):
        tm = TrafficManager()
        pods = ["pod-c", "pod-a", "pod-b", "pod-d"]
        first = tm._deterministic_pick(pods, 2)
        second = tm._deterministic_pick(list(reversed(pods)), 2)
        assert first == second
        assert len(first) == 2

    def test_build_service_selector_validates(self):
        tm = TrafficManager()
        assert tm._build_service_selector(key="k", value="v") == {"k": "v"}
        with pytest.raises(ValueError):
            tm._build_service_selector(key="", value="v")
        with pytest.raises(ValueError):
            tm._build_service_selector(key="k", value="")

    def test_verify_service_updated_success(self):
        tm = TrafficManager()
        resp = {"status": "SUCCESS", "data": {"after_selector": {"k": "v"}}}
        tm._verify_service_updated(resp, {"k": "v"})

    def test_verify_service_updated_mismatch_raises(self):
        tm = TrafficManager()
        resp = {"status": "SUCCESS", "data": {"after_selector": {"k": "x"}}}
        with pytest.raises(Exception):
            tm._verify_service_updated(resp, {"k": "v"})

