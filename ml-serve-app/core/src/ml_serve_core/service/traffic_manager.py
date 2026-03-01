from __future__ import annotations

import hashlib
import asyncio
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from ml_serve_core.client.dcm_client import DCMClient
from ml_serve_core.dtos.dtos import EnvConfig
from ml_serve_model import Environment


@dataclass(frozen=True)
class TrafficSplitResult:
    success: bool
    target_weight: int
    actual_weight: int
    error: Optional[str] = None


class TrafficManager:
    """
    Traffic management via DCM-backed Service selector updates.

    In this repo's architecture, DCM is the only component that talks to the
    Kubernetes API server, so all Service patching goes through DCM.
    """

    def __init__(self):
        self.dcm_client = DCMClient()

    @staticmethod
    def _stable_hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def _select_count_for_weight(cls, total: int, weight_percent: int) -> int:
        if total <= 0:
            return 0
        if weight_percent <= 0:
            return 0
        if weight_percent >= 100:
            return total
        return int(round(total * (weight_percent / 100.0)))

    @classmethod
    def _deterministic_pick(cls, pod_names: list[str], pick: int) -> list[str]:
        ordered = sorted(pod_names, key=lambda n: cls._stable_hash(n))
        return ordered[: max(0, min(pick, len(ordered)))]

    @staticmethod
    def _build_service_selector(*, key: str, value: str) -> dict[str, str]:
        if not key or not value:
            raise ValueError("selector key/value must be non-empty")
        return {key: value}

    async def _update_selector_with_retry(
        self,
        *,
        env: Environment,
        service_name: str,
        selector: dict[str, str],
        retries: int = 3,
        base_delay_s: float = 0.5,
    ) -> None:
        env_config = EnvConfig(**env.env_configs)
        last_exc: Optional[Exception] = None
        for attempt in range(max(1, retries)):
            try:
                resp = await self.dcm_client.update_service_selector(
                    resource_id=service_name,
                    kube_cluster=env_config.cluster_name,
                    namespace=env_config.namespace,
                    service_selector=selector,
                )
                self._verify_service_updated(resp, selector)
                return
            except Exception as exc:
                last_exc = exc
                if attempt < retries - 1:
                    await asyncio.sleep(base_delay_s * (2 ** attempt))
        if last_exc:
            raise last_exc

    async def set_service_selector_for_release(
        self,
        *,
        env: Environment,
        resource_id: str,
        artifact_id: str,
        darwin_resource: str,
        selector: dict[str, str],
    ) -> None:
        """
        Set Service selector for a Helm-managed release and verify via DCM service patch.

        We update Helm values to keep desired state stable across upgrades, then
        we idempotently patch the Service via DCM to confirm the selector applied.
        """
        env_config = EnvConfig(**env.env_configs)
        await self.dcm_client.update_resource(values={"service": {"selector": selector}}, artifact_id=artifact_id, darwin_resource=darwin_resource)
        await self.dcm_client.start_resource(
            resource_id=resource_id,
            kube_cluster=env_config.cluster_name,
            namespace=env_config.namespace,
            artifact_id=artifact_id,
            darwin_resource=darwin_resource,
        )
        await self._update_selector_with_retry(env=env, service_name=resource_id, selector=selector)

    @staticmethod
    def _verify_service_updated(resp: object, desired_selector: dict[str, str]) -> None:
        """
        Confirm DCM applied the desired selector.

        Expected DCM response (best-effort):
        {"status":"SUCCESS","data":{"after_selector":{...}}}
        """
        if not isinstance(resp, dict):
            return
        data = resp.get("data")
        if not isinstance(data, dict):
            return
        after = data.get("after_selector")
        if not isinstance(after, dict):
            return
        if after != desired_selector:
            raise Exception(f"Service selector verification failed. desired={desired_selector} actual={after}")

    async def apply_traffic_split(
        self,
        *,
        env: Environment,
        service_name: str,
        target_new_weight: int,
        old_pod_names: list[str],
        new_pod_names: list[str],
        old_selector_key: str,
        new_selector_key: str,
    ) -> TrafficSplitResult:
        """
        Apply a traffic split by selecting pods from old/new versions.

        Current implementation is selector-key based (expects the chart to label
        pods such that a Service selector can match subsets). The exact label
        strategy is finalized in strategy implementations.
        """
        try:
            target_new_weight = int(target_new_weight)
        except Exception:
            return TrafficSplitResult(False, target_new_weight=0, actual_weight=0, error="target_new_weight must be int")

        target_new_weight = max(0, min(100, target_new_weight))

        total = len(old_pod_names) + len(new_pod_names)
        if total == 0:
            return TrafficSplitResult(False, target_new_weight, 0, error="No pods available for traffic split")

        new_pick = self._select_count_for_weight(total=len(new_pod_names), weight_percent=target_new_weight)
        old_pick = max(0, min(len(old_pod_names), total - new_pick))

        picked_new = self._deterministic_pick(new_pod_names, new_pick)
        picked_old = self._deterministic_pick(old_pod_names, old_pick)

        # With deterministic pod selection, weights are approximate; compute achieved.
        actual_total = len(picked_old) + len(picked_new)
        actual_weight = int(round((len(picked_new) / actual_total) * 100)) if actual_total else 0

        if actual_weight != target_new_weight:
            logger.info(
                f"Traffic split rounding: target={target_new_weight}% actual={actual_weight}% "
                f"(old={len(picked_old)} new={len(picked_new)})"
            )

        # Selector model (best-effort until DCM endpoint is deployed):
        # Strategies decide how pods are labeled; we only patch the Service selector.
        selector_value = new_selector_key if target_new_weight >= 50 else old_selector_key
        service_selector = self._build_service_selector(key="deploy.darwin.io/traffic", value=selector_value)
        await self._update_selector_with_retry(env=env, service_name=service_name, selector=service_selector)

        return TrafficSplitResult(True, target_new_weight, actual_weight, error=None)

