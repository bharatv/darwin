import os

CREDENTIALS_FILE_PATH = "~/.hermes/credential.txt"
DEFAULT_TOKEN = 'darwin-local-admin-token'

CONFIGS_MAP = {
    "local": {
        "hermes_deployer_url": "http://localhost/ml-serve",
        "feature_store_url": "http://localhost/feature-store",
    },
    "darwin-local": {
        "hermes_deployer_url": "http://localhost/ml-serve",
        "feature_store_url": "http://localhost/feature-store",
    }
}
