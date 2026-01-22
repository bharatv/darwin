# Wine Classification - Spark Data Processing + LightGBM Training

This example demonstrates the complete ML lifecycle on the Darwin platform using a hybrid approach: **Spark for data processing** and **native LightGBM for model training**.

## Overview

You will learn how to:
1. Set up the Darwin ML platform with required services
2. Create and manage a compute cluster with Spark support
3. Use Spark for distributed data processing (ETL, splitting)
4. Train a LightGBM model using native LightGBM
5. Track experiments and register models with MLflow
6. Deploy models for inference using ML-Serve
7. Test inference endpoints and clean up resources

## Why This Approach?

- **Spark**: Handles data processing and can scale to large datasets
- **Native LightGBM**: Efficient gradient boosting on the driver node
- **MLflow lightgbm flavor**: Reliable model logging and versioning
- **Fast serving**: No Spark/Java dependencies needed at inference time

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Darwin ML Platform                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │   Compute    │    │    MLflow    │    │   ML-Serve   │               │
│  │   Cluster    │───▶│   Registry   │───▶│  Deployment  │               │
│  │  (Ray+Spark) │    │              │    │              │               │
│  └──────────────┘    └──────────────┘    └──────────────┘               │
│         │                   │                   │                        │
│         ▼                   ▼                   ▼                        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │ Jupyter Lab  │    │   Model      │    │  Inference   │               │
│  │  Notebook    │    │   Artifacts  │    │   Endpoint   │               │
│  └──────────────┘    └──────────────┘    └──────────────┘               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Dataset

The Wine dataset contains 178 samples of wine from three different cultivars with 13 physicochemical features:

| Feature | Description |
|---------|-------------|
| alcohol | Alcohol content |
| malic_acid | Malic acid content |
| ash | Ash content |
| alcalinity_of_ash | Alcalinity of ash |
| magnesium | Magnesium content |
| total_phenols | Total phenols |
| flavanoids | Flavanoids content |
| nonflavanoid_phenols | Non-flavanoid phenols |
| proanthocyanins | Proanthocyanins content |
| color_intensity | Color intensity |
| hue | Hue |
| od280_od315_of_diluted_wines | OD280/OD315 ratio |
| proline | Proline content |

## Prerequisites

- Docker installed and running
- `kubectl` CLI installed
- Python 3.9.7+
- At least 8GB RAM available for the local cluster

---

## Step 1: Initialize Platform Configuration

Run the example initialization script to configure the required services:

```bash
# From the project root directory
cd /path/to/darwin

# Run the example init script
sh examples/lightgbm-wine-classification/init-example.sh
```

This enables:
- **Compute**: `darwin-compute`, `darwin-cluster-manager`
- **MLflow**: `darwin-mlflow`, `darwin-mlflow-app`
- **Serve**: `ml-serve-app`, `artifact-builder`
- **Runtime**: `ray:2.37.0` with Darwin SDK (Spark support)
- **CLI**: `darwin-cli`

Alternatively, run `./init.sh` manually and select:
- Compute: Yes
- MLflow: Yes
- Serve: Yes
- Darwin SDK Runtime: Yes
- Ray runtime `ray:2.37.0`: Yes
- Darwin CLI: Yes

---

## Step 2: Build and Deploy Platform

Build all required images and set up the local Kubernetes cluster:

```bash
# Build images (answer 'y' to prompts, or use -y for auto-yes)
./setup.sh -y

# Deploy the platform
./start.sh
```

Wait for all pods to be ready. You can check status with:

```bash
export KUBECONFIG=./.setup/kindkubeconfig.yaml
kubectl get pods -n darwin
```

---

## Step 3: Configure Darwin CLI

Activate the virtual environment and configure the CLI:

```bash
# Activate virtual environment
source .venv/bin/activate

# Configure CLI environment
darwin config set --env darwin-local

# Verify CLI is working
darwin --help
```

---

## Step 4: Create Compute Cluster

Create a compute cluster with Spark support using the provided configuration:

```bash
darwin compute create --file examples/lightgbm-wine-classification/cluster-config.yaml
```

Expected output:
```
Cluster created successfully!
Cluster ID: <CLUSTER_ID>
Name: wine-lightgbm-spark-example
Status: PENDING
```

Save the `CLUSTER_ID` for later steps:

```bash
export CLUSTER_ID=<your-cluster-id>

# Wait for cluster to be active (this may take a few minutes)
darwin compute get --cluster-id $CLUSTER_ID
```

Wait until the cluster status shows `active`.

---

## Step 5: Access Jupyter Lab

Once the cluster is active, access Jupyter Lab in your browser:

```
http://localhost/kind-0/{CLUSTER_ID}-jupyter/lab
```

Replace `{CLUSTER_ID}` with your actual cluster ID.

---

## Step 6: Run Training Notebook

In Jupyter Lab:

1. Create a new Python 3 notebook or upload `train_lightgbm_wine_spark.ipynb`

2. If creating a new notebook, copy the cells from `train_lightgbm_wine_spark.ipynb`:

**Cell 1: Install Dependencies**
```python
# Fix pyOpenSSL/cryptography compatibility issue first
%pip install --upgrade pyOpenSSL cryptography

# Install main dependencies (pin MLflow to match server version)
%pip install lightgbm pandas numpy scikit-learn mlflow==2.12.2 pyspark
```

**Cell 2: Import Libraries**
```python
import os
import json
import tempfile
import numpy as np
import pandas as pd
from datetime import datetime

# LightGBM imports
import lightgbm as lgb

# Spark imports (for data processing only)
from pyspark.sql import SparkSession
from pyspark.sql.functions import col

# MLflow imports
import mlflow
import mlflow.lightgbm
from mlflow import set_tracking_uri, set_experiment
from mlflow.client import MlflowClient
from mlflow.models import infer_signature

# Scikit-learn imports (for loading dataset and metrics)
from sklearn.datasets import load_wine
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

# Darwin SDK imports (optional - only available on Darwin cluster)
DARWIN_SDK_AVAILABLE = False
try:
    import ray
    from darwin import init_spark_with_configs, stop_spark
    DARWIN_SDK_AVAILABLE = True
    print("Darwin SDK available - will use distributed Spark on Darwin cluster")
except ImportError as e:
    print(f"Darwin SDK not available: {e}")
    print("Running in LOCAL mode - will use local Spark session")
```

**Cell 3: Initialize Spark with Darwin SDK**
```python
# Spark configurations
spark_configs = {
    "spark.sql.execution.arrow.pyspark.enabled": "true",
    "spark.sql.session.timeZone": "UTC",
    "spark.sql.shuffle.partitions": "4",
    "spark.default.parallelism": "4",
    "spark.executor.memory": "2g",
    "spark.executor.cores": "1",
    "spark.driver.memory": "2g",
    "spark.executor.instances": "2",
}

ray.init()
spark = init_spark_with_configs(spark_configs=spark_configs)
print(f"Spark version: {spark.version}")
```

**Cell 4: Setup MLflow**
```python
MLFLOW_URI = "http://darwin-mlflow-lib.darwin.svc.cluster.local:8080"
USERNAME = "abc@gmail.com"
PASSWORD = "password"
EXPERIMENT_NAME = "wine_spark_lightgbm_classification"
MODEL_NAME = "WineLightGBMSparkClassifier"

os.environ["MLFLOW_TRACKING_USERNAME"] = USERNAME
os.environ["MLFLOW_TRACKING_PASSWORD"] = PASSWORD
set_tracking_uri(MLFLOW_URI)
client = MlflowClient(MLFLOW_URI)
set_experiment(experiment_name=EXPERIMENT_NAME)
print(f"MLflow configured: {MLFLOW_URI}")
```

**Cell 5: Load and Prepare Data with Spark**
```python
# Load Wine dataset
data = load_wine(as_frame=True)
pdf = data.data.copy()
pdf['label'] = data.target

feature_names = data.feature_names

print(f"Dataset: Wine")
print(f"Samples: {len(pdf):,}")
print(f"Features: {len(feature_names)}")

print(f"\nFeature names:")
for i, col_name in enumerate(feature_names, 1):
    print(f"  {i}. {col_name}")

print(f"\nTarget distribution:")
for class_idx in range(3):
    count = (pdf['label'] == class_idx).sum()
    print(f"  Class {class_idx}: {count} samples")

# Use Spark for distributed data splitting (demonstrates Spark processing)
print("\nUsing Spark for distributed data splitting...")
spark_df = spark.createDataFrame(pdf)
train_spark, test_spark = spark_df.randomSplit([0.8, 0.2], seed=42)

# Collect to pandas for LightGBM training
print("Collecting to pandas for training...")
train_pdf = train_spark.toPandas()
test_pdf = test_spark.toPandas()

print(f"\nTrain samples: {len(train_pdf):,}")
print(f"Test samples: {len(test_pdf):,}")
```

**Cell 6: Train Model with Native LightGBM**
```python
# Define hyperparameters
hyperparams = {
    "objective": "multiclass",
    "num_class": 3,
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "num_iterations": 100,
}

# Prepare data
X_train = train_pdf[feature_names].values
y_train = train_pdf["label"].values
X_test = test_pdf[feature_names].values
y_test = test_pdf["label"].values

# Get sample input for MLflow logging
sample_input = train_pdf[feature_names].head(1)

with mlflow.start_run(run_name=f"lightgbm_wine_{datetime.now().strftime('%Y%m%d_%H%M%S')}"):
    # Create LightGBM datasets
    train_data = lgb.Dataset(X_train, label=y_train, feature_name=list(feature_names))
    test_data = lgb.Dataset(X_test, label=y_test, feature_name=list(feature_names), reference=train_data)
    
    # LightGBM parameters
    params = {
        "objective": hyperparams["objective"],
        "num_class": hyperparams["num_class"],
        "num_leaves": hyperparams["num_leaves"],
        "learning_rate": hyperparams["learning_rate"],
        "feature_fraction": hyperparams["feature_fraction"],
        "bagging_fraction": hyperparams["bagging_fraction"],
        "bagging_freq": hyperparams["bagging_freq"],
        "verbose": -1,
        "seed": 42,
    }
    
    # Train model
    print("Training LightGBM model...")
    model = lgb.train(
        params,
        train_data,
        num_boost_round=hyperparams["num_iterations"],
        valid_sets=[train_data, test_data],
        valid_names=["train", "test"],
    )
    print("Training completed!")
    
    # Make predictions
    test_proba = model.predict(X_test)
    test_pred = np.argmax(test_proba, axis=1)
    
    # Calculate metrics
    accuracy = accuracy_score(y_test, test_pred)
    precision = precision_score(y_test, test_pred, average="weighted")
    recall = recall_score(y_test, test_pred, average="weighted")
    f1 = f1_score(y_test, test_pred, average="weighted")
    
    # Log to MLflow
    mlflow.log_params(hyperparams)
    mlflow.log_param("training_framework", "lightgbm")
    mlflow.log_param("data_processing", "spark")
    mlflow.log_metric("test_accuracy", accuracy)
    mlflow.log_metric("test_precision", precision)
    mlflow.log_metric("test_recall", recall)
    mlflow.log_metric("test_f1", f1)
    
    # Log LightGBM model using mlflow.lightgbm (IMPORTANT!)
    sample_output = pd.DataFrame({"prediction": [0]})
    signature = infer_signature(sample_input, sample_output)
    
    mlflow.lightgbm.log_model(
        lgb_model=model,
        artifact_path="model",
        signature=signature,
        input_example=sample_input
    )
    
    run_id = mlflow.active_run().info.run_id
    experiment_id = mlflow.active_run().info.experiment_id
    
    print(f"\nTest Accuracy: {accuracy:.4f}")
    print(f"Test Precision: {precision:.4f}")
    print(f"Test Recall: {recall:.4f}")
    print(f"Test F1: {f1:.4f}")
    print(f"Run ID: {run_id}")
```

**Cell 7: Register Model**
```python
model_uri = f"runs:/{run_id}/model"

# Create registered model if needed
try:
    client.get_registered_model(MODEL_NAME)
    print(f"Model '{MODEL_NAME}' exists")
except:
    client.create_registered_model(MODEL_NAME)
    print(f"Created model: {MODEL_NAME}")

# Register version
result = client.create_model_version(
    name=MODEL_NAME,
    source=model_uri,
    run_id=run_id
)
print(f"Registered {MODEL_NAME} version {result.version}")
print(f"\nModel URI for deployment: models:/{MODEL_NAME}/{result.version}")
```

**Cell 8: Cleanup Spark**
```python
# Cleanup: Stop Spark session properly
if DARWIN_SDK_AVAILABLE:
    stop_spark()
else:
    spark.stop()
print("Spark session stopped")
```

3. Run all cells in sequence

4. Note the **Run ID**, **Experiment ID**, and **Model Version** from the output

---

## Step 7: Verify MLflow Model Registration

Back in your terminal, verify the model was registered:

```bash
# List all registered models
darwin mlflow model list

# Get details of the wine model
darwin mlflow model get --name WineLightGBMSparkClassifier

# Get specific version details
darwin mlflow model get --name WineLightGBMSparkClassifier --version 1
```

Expected output:
```
Model: WineLightGBMSparkClassifier
Latest Version: 1
Description: Wine LightGBM Classifier
```

---

## Step 8: Stop the Compute Cluster

After training is complete, stop the cluster to free resources:

```bash
darwin compute stop --cluster-id $CLUSTER_ID
```

Verify the cluster is stopped:

```bash
darwin compute get --cluster-id $CLUSTER_ID
```

---

## Step 9: Configure Serve Authentication

Before using serve commands, configure your authentication token:

```bash
# Configure with default darwin-local token (recommended for local development)
darwin serve configure
```

---

## Step 10: Create Serve Environment

Create the serve environment if it doesn't exist:

```bash
darwin serve environment create \
  --name darwin-local \
  --domain-suffix .local \
  --cluster-name kind \
  --namespace serve
```

If the environment already exists, you'll see a message indicating it's already configured.

---

## Step 11: Create ML-Serve Application

Create a new serve application for the model:

```bash
darwin serve create \
  --name wine-lightgbm-classifier \
  --type api \
  --space ml-examples \
  --description "Wine LightGBM Spark Classifier"
```

---

## Step 12: Deploy the Model

Deploy the model using the MLflow model URI:

```bash
darwin serve deploy-model \
  --serve-name wine-lightgbm-classifier \
  --artifact-version v1.0.0 \
  --model-uri models:/WineLightGBMClassifier/1 \
  --env darwin-local \
  --cores 2 \
  --memory 4 \
  --node-capacity ondemand \
  --min-replicas 1 \
  --max-replicas 3
```

---

## Step 13: Test Inference

Test the deployed model with sample requests:

**Using curl:**

```bash
curl -X POST http://localhost/wine-lightgbm-classifier/predict \
  -H "Content-Type: application/json" \
  -d @examples/lightgbm-wine-classification/sample-request.json
```

**Sample request payload:**

```json
{
  "features": {
    "alcohol": 12.85,
    "malic_acid": 1.6,
    "ash": 2.52,
    "alcalinity_of_ash": 17.8,
    "magnesium": 95,
    "total_phenols": 2.48,
    "flavanoids": 2.37,
    "nonflavanoid_phenols": 0.26,
    "proanthocyanins": 1.46,
    "color_intensity": 3.93,
    "hue": 1.09,
    "od280/od315_of_diluted_wines": 3.63,
    "proline": 1015
  }
}
```

**Expected response:**

```json
{
  "scores": [
    [
      0.982170003685416,
      0.015241154331924857,
      0.002588841982659213
    ]
  ]
}
```

**Test with different wine samples:**

```bash
# Class 0 sample (cultivar 0)
curl -X POST http://localhost/wine-lightgbm-classifier/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": {
      "alcohol": 14.23,
      "malic_acid": 1.71,
      "ash": 2.43,
      "alcalinity_of_ash": 15.6,
      "magnesium": 127,
      "total_phenols": 2.8,
      "flavanoids": 3.06,
      "nonflavanoid_phenols": 0.28,
      "proanthocyanins": 2.29,
      "color_intensity": 5.64,
      "hue": 1.04,
      "od280/od315_of_diluted_wines": 3.92,
      "proline": 1065
    }
  }'

# Class 1 sample (cultivar 1)
curl -X POST http://localhost/wine-lightgbm-classifier/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": {
      "alcohol": 12.37,
      "malic_acid": 1.13,
      "ash": 2.16,
      "alcalinity_of_ash": 19.0,
      "magnesium": 87,
      "total_phenols": 3.5,
      "flavanoids": 3.1,
      "nonflavanoid_phenols": 0.19,
      "proanthocyanins": 1.87,
      "color_intensity": 4.45,
      "hue": 1.22,
      "od280/od315_of_diluted_wines": 2.87,
      "proline": 420
    }
  }'

# Class 2 sample (cultivar 2)
curl -X POST http://localhost/wine-lightgbm-classifier/predict \
  -H "Content-Type: application/json" \
  -d '{
    "features": {
      "alcohol": 13.11,
      "malic_acid": 1.01,
      "ash": 1.7,
      "alcalinity_of_ash": 15.0,
      "magnesium": 78,
      "total_phenols": 2.98,
      "flavanoids": 3.18,
      "nonflavanoid_phenols": 0.26,
      "proanthocyanins": 2.28,
      "color_intensity": 5.3,
      "hue": 1.12,
      "od280/od315_of_diluted_wines": 3.18,
      "proline": 502
    }
  }'
```

---

## Step 14: Undeploy the Serve Application

When done, undeploy the serve application:

```bash
darwin serve undeploy-model --serve-name wine-lightgbm-classifier --env darwin-local
```

---

## Step 15: Cleanup (Optional)

Delete the compute cluster:

```bash
darwin compute delete --cluster-id $CLUSTER_ID
```

---

## Summary

In this example, you learned how to:

| Step | Action | CLI Command |
|------|--------|-------------|
| 1 | Initialize platform | `sh init-example.sh` |
| 2 | Build and deploy | `./setup.sh -y && ./start.sh` |
| 3 | Configure CLI | `darwin config set --env darwin-local` |
| 4 | Create cluster | `darwin compute create --file cluster-config.yaml` |
| 5 | Access Jupyter | Browser: `http://localhost/kind-0/{cluster_id}-jupyter/lab` |
| 6 | Train model | Run notebook cells (hybrid Spark + LightGBM) |
| 7 | Verify model | `darwin mlflow model get --name WineLightGBMClassifier` |
| 8 | Stop cluster | `darwin compute stop --cluster-id $CLUSTER_ID` |
| 9 | Configure serve auth | `darwin serve configure` |
| 10 | Create environment | `darwin serve environment create ...` |
| 11 | Create serve app | `darwin serve create --name wine-lightgbm-classifier ...` |
| 12 | Deploy model | `darwin serve deploy-model ...` |
| 13 | Test inference | `curl -X POST .../predict` |
| 14 | Undeploy | `darwin serve undeploy-model ...` |

---

## Comparison: LightGBM vs Random Forest (Iris Example)

| Aspect | This Example (LightGBM Wine) | Iris Example (Sklearn RF) |
|--------|------------------------------|-------------------------|
| Algorithm | LightGBM (Gradient Boosting) | Sklearn Random Forest |
| Training | Hybrid: Spark data prep + LightGBM | Hybrid: Spark data prep + Sklearn |
| Data Prep | Spark DataFrames | Spark DataFrames |
| Dataset | Wine (178 samples, 13 features) | Iris (150 samples, 4 features) |
| Use Case | Medium datasets, high accuracy | Medium datasets, classification |

---

## Troubleshooting

### Cluster not starting

```bash
# Check cluster manager logs
kubectl logs -n darwin -l app=darwin-cluster-manager

# Check compute service logs
kubectl logs -n darwin -l app=darwin-compute
```

### MLflow connection issues

```bash
# Verify MLflow service is running
kubectl get pods -n darwin -l app=darwin-mlflow-lib

# Check MLflow app logs
kubectl logs -n darwin -l app=darwin-mlflow-app
```

### LightGBM import errors

If you see LightGBM import errors in the notebook:

```python
# Install LightGBM with pip
%pip install lightgbm --upgrade
```

### Serve deployment failing

```bash
# Check artifact builder status
darwin serve artifact jobs

# Check ml-serve-app logs
kubectl logs -n darwin -l app=ml-serve-app
```

### Port forwarding issues

```bash
# Restart ingress
kubectl rollout restart deployment -n ingress-nginx ingress-nginx-controller
```

---

## Files in This Example

| File | Description |
|------|-------------|
| `README.md` | This guide |
| `train_lightgbm_wine_spark.ipynb` | Hybrid training notebook (Spark + LightGBM) |
| `train_lightgbm_wine.ipynb` | Alternative non-distributed version |
| `init-example.sh` | Quick setup script |
| `cluster-config.yaml` | Compute cluster configuration |
| `serve-config.yaml` | ML-Serve infrastructure config |
| `sample-request.json` | Sample inference request |
