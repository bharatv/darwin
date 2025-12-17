from __future__ import annotations

from typeguard import typechecked
from mlflow_app_layer.config.constants import CONFIG_MAP


@typechecked
class Config:
    """
    Config class to get the configuration based on environment
    """

    def __init__(self):
        self._config = CONFIG_MAP
        print(f"Config: {self._config}")

    @property
    def mlflow_ui_url(self):
        return self._config["MLFLOW_UI_URL"]

    @property
    def mlflow_app_layer_url(self):
        return self._config["MLFLOW_APP_LAYER_URL"]

    @property
    def mlflow_app_base_path(self):
        return self._config["MLFLOW_APP_BASE_PATH"]

    def mlflow_admin_credentials(self) -> dict:
        return {
            "username": self._config["MLFLOW_ADMIN_USERNAME"],
            "password": self._config["MLFLOW_ADMIN_PASSWORD"],
        }

    def db_config(self) -> dict:
        mysql_db = self._config["mysql_db"]  # type: ignore[index]
        return {
            "host": mysql_db["host"],  # type: ignore[index]
            "user": mysql_db["username"],  # type: ignore[index]
            "password": mysql_db["password"],  # type: ignore[index]
            "database": mysql_db["database"],  # type: ignore[index]
            "port": mysql_db["port"],  # type: ignore[index]
        }
