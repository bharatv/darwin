import pytest
from unittest.mock import AsyncMock

from ml_serve_core.service.traffic_manager import TrafficManager


@pytest.mark.unit
class TestTrafficManagerRetry:
    @pytest.mark.asyncio
    async def test_update_selector_with_retry_eventually_succeeds(self, db_session, test_environment):
        tm = TrafficManager()

        calls = {"n": 0}

        async def flaky_update_service_selector(*, resource_id: str, kube_cluster: str, namespace: str, service_selector: dict):
            calls["n"] += 1
            if calls["n"] < 2:
                raise Exception("temporary")
            return {"status": "SUCCESS", "data": {"after_selector": service_selector}}

        tm.dcm_client = AsyncMock()
        tm.dcm_client.update_service_selector = AsyncMock(side_effect=flaky_update_service_selector)

        await tm._update_selector_with_retry(
            env=test_environment,
            service_name="svc",
            selector={"k": "v"},
            retries=3,
            base_delay_s=0.0,
        )
        assert calls["n"] == 2

