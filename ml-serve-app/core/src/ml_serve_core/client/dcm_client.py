import json
import traceback

from ml_serve_core.client.http_client import AsyncHttpClient
from ml_serve_core.config.configs import Config
from loguru import logger


class DCMClient:
    def __init__(self):
        self.config = Config()

    async def build_resource(
            self, darwin_resource: str, values: dict, version: str, artifact_id: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/"
            data = {
                "darwin_resource": darwin_resource,
                "values": values,
                "version": version,
                "artifact_id": artifact_id
            }

            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error  while calling DCM create resource api: {e} with traceback: {tb}")
            raise Exception("Error while building resource")

    async def update_resource(
            self, values: dict, artifact_id: str, darwin_resource: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/values"
            data = {
                "values": values,
                "artifact_id": artifact_id,
                "darwin_resource": darwin_resource
            }
            async with AsyncHttpClient() as client:
                resp = await client.patch(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM update resource api: {e} with traceback: {tb}")
            raise Exception("Error while updating resource")

    async def start_resource(
            self, resource_id: str, kube_cluster: str, namespace: str, artifact_id: str, darwin_resource: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/start"
            data = {
                "resource_id": resource_id,
                "kube_cluster": kube_cluster,
                "kube_namespace": namespace,
                "artifact_id": artifact_id,
                "darwin_resource": darwin_resource
            }
            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM start resource api: {e} with traceback: {tb}")
            raise Exception("Error while starting resource")

    async def stop_resource(
            self, resource_id: str, kube_cluster: str, namespace: str
    ):
        try:
            url = self.config.dcm_url + "/resource-instance/stop"
            data = {
                "resource_id": resource_id,
                "kube_cluster": kube_cluster,
                "kube_namespace": namespace
            }
            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM stop resource api: {e} with traceback: {tb}")
            raise Exception("Error while stopping resource")

    async def get_status(self, resource_id: str, kube_cluster: str, kube_namespace: str):
        try:
            url = self.config.dcm_url + f"/resource-instance/status"
            data = {
                "resource_id": resource_id,
                "kube_cluster": kube_cluster,
                "kube_namespace": kube_namespace
            }
            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]['data']['status']
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM get status api: {e} with traceback: {tb}")
            raise Exception("Error while getting status")

    async def update_service_selector(
            self,
            *,
            resource_id: str,
            kube_cluster: str,
            namespace: str,
            service_selector: dict,
    ):
        """
        Best-effort API for patching a Kubernetes Service selector via DCM.

        NOTE: The corresponding DCM endpoint is introduced as part of the
        deployment strategies work. Until DCM is updated, callers should
        expect this to fail and handle exceptions.
        """
        try:
            url = self.config.dcm_url + "/resource-instance/update-service"
            data = {
                "resource_id": resource_id,
                "kube_cluster": kube_cluster,
                "kube_namespace": namespace,
                "service_selector": service_selector,
            }
            async with AsyncHttpClient() as client:
                resp = await client.post(url, json=data)
                return resp["body"]
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error while calling DCM update service api: {e} with traceback: {tb}")
            raise Exception("Error while updating service selector")
