#!/usr/bin/env bash
set -e

echo "BASE_DIR: $BASE_DIR"
echo "SERVICE_NAME: $SERVICE_NAME"
echo "DEPLOYMENT_TYPE: $DEPLOYMENT_TYPE"
echo "APP_DIR: $APP_DIR"

REQUIRED_VARS=("BASE_DIR" "SERVICE_NAME" "DEPLOYMENT_TYPE" "APP_DIR")
MISSING_VARS=()
for VAR in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!VAR}" ]]; then
    echo "ERROR: Environment variable $VAR is not set"
    MISSING_VARS+=("$VAR")
  fi
done

if [[ ${#MISSING_VARS[@]} -ne 0 ]]; then
  echo "The following required environment variables are missing: ${MISSING_VARS[*]}"
  exit 1
fi

# This is to install git in the containers for the deployment type container
if [[ "$DEPLOYMENT_TYPE" == "container" ]]; then
  ls -la
  python3 -m venv .
  source bin/activate
  bin/python3 -m pip install --upgrade pip
  export PATH=$PATH:"$BASE_DIR"/bin
  bin/pip3 install -e app_layer/. --force-reinstall
  # Install mlflow first, then override dependencies with pinned versions
  bin/pip3 install "mlflow[auth]==2.12.2" --force-reinstall
  bin/pip3 install mlflow==2.12.2 --force-reinstall
  # Override dependencies with pinned versions after mlflow installation
  bin/pip3 install urllib3==1.26.6 --force-reinstall
  bin/pip3 install protobuf==3.20.3 --force-reinstall
  bin/pip3 install requests==2.31.0 --force-reinstall
  bin/pip3 install pymysql==1.0.2 --force-reinstall
  bin/pip3 install cryptography==43.0.1 --force-reinstall
  bin/pip3 install boto3 --force-reinstall
  echo "Requirements installed"
else
  # In local mode, check if SERVICE_NAME subdirectory exists
  # If not, files are directly in BASE_DIR (e.g., GitHub CI)
  if [ -d "$BASE_DIR/$SERVICE_NAME" ]; then
    cd "$BASE_DIR/$SERVICE_NAME" || exit
  else
    cd "$BASE_DIR" || exit
  fi
  pip3 install -e app_layer/. --force-reinstall
  # Install mlflow first, then override dependencies with pinned versions
  pip install "mlflow[auth]==2.12.2" --force-reinstall
  pip3 install mlflow==2.12.2 --force-reinstall
  # Override dependencies with pinned versions after mlflow installation
  pip3 install urllib3==1.26.6 --force-reinstall
  pip3 install protobuf==3.20.3 --force-reinstall
  pip3 install requests==2.31.0 --force-reinstall
  pip3 install pymysql==1.0.2 --force-reinstall
  pip3 install cryptography==43.0.1 --force-reinstall
  pip3 install boto3 --force-reinstall
  echo "Requirements installed"
fi