# Iris Classification - Spark Data Processing + Sklearn Training

This example demonstrates the complete ML lifecycle on the Darwin platform using a hybrid approach: **Spark for data processing** and **scikit-learn for model training**.

## Overview

You will learn how to:
1. Set up the Darwin ML platform with required services
2. Create and manage a compute cluster with Spark support
3. Use Spark for distributed data processing (ETL, splitting)
4. Train a Random Forest model using scikit-learn
5. Track experiments and register models with MLflow
6. Deploy models for inference using ML-Serve
7. Test inference endpoints and clean up resources

## Why This Approach?

- **Spark**: Handles data processing and can scale to large datasets
- **Scikit-learn**: Reliable model training with excellent MLflow integration
- **MLflow sklearn flavor**: Works seamlessly with any MLflow server version
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
sh examples/iris-classification/init-example.sh
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
darwin compute create --file examples/iris-classification/cluster-config.yaml
```

Expected output:
```
Cluster created successfully!
Cluster ID: <CLUSTER_ID>
Name: iris-spark-example
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

1. Create a new Python 3 notebook or upload `train_iris_model_spark.ipynb`

2. If creating a new notebook, copy the cells from `train_iris_model_spark.ipynb`:

**Cell 1: Install Dependencies**
```python
# Fix pyOpenSSL/cryptography compatibility issue first
%pip install --upgrade pyOpenSSL cryptography

# Install main dependencies (pin MLflow to match server version)
%pip install pandas numpy scikit-learn mlflow==2.12.2 pyspark
```

**Cell 2: Import Libraries**
```python
import os
import json
import tempfile
import numpy as np
import pandas as pd
from datetime import datetime

# Spark imports (for data processing only)
from pyspark.sql import SparkSession

# MLflow imports
import mlflow
import mlflow.sklearn
from mlflow import set_tracking_uri, set_experiment
from mlflow.client import MlflowClient
from mlflow.models import infer_signature

# Scikit-learn imports (for training and metrics)
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

# Darwin SDK imports
import ray
from darwin import init_spark_with_configs, stop_spark

print("Darwin SDK available - will use distributed Spark on Darwin cluster")
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
EXPERIMENT_NAME = "iris_spark_sklearn_classification"
MODEL_NAME = "IrisSklearnRFClassifier"

os.environ["MLFLOW_TRACKING_USERNAME"] = USERNAME
os.environ["MLFLOW_TRACKING_PASSWORD"] = PASSWORD
set_tracking_uri(MLFLOW_URI)
client = MlflowClient(MLFLOW_URI)
set_experiment(experiment_name=EXPERIMENT_NAME)
print(f"MLflow configured: {MLFLOW_URI}")
```

**Cell 5: Load and Prepare Data with Spark**
```python
# Load Iris dataset
iris = load_iris(as_frame=True)
pdf = iris.data.copy()
pdf.columns = ['sepal_length', 'sepal_width', 'petal_length', 'petal_width']
pdf['label'] = iris.target
target_names = iris.target_names.tolist()
feature_names = ['sepal_length', 'sepal_width', 'petal_length', 'petal_width']

print(f"Dataset: Iris")
print(f"Samples: {len(pdf):,}")
print(f"Features: {len(feature_names)}")

# Use Spark for distributed data splitting (demonstrates Spark processing)
print("\nUsing Spark for distributed data splitting...")
spark_df = spark.createDataFrame(pdf)
train_spark, test_spark = spark_df.randomSplit([0.8, 0.2], seed=42)

# Collect to pandas for sklearn training
print("Collecting to pandas for training...")
train_pdf = train_spark.toPandas()
test_pdf = test_spark.toPandas()

print(f"\nTrain samples: {len(train_pdf):,}")
print(f"Test samples: {len(test_pdf):,}")
```

**Cell 6: Train Model with Scikit-learn**
```python
# Define hyperparameters
hyperparams = {
    "n_estimators": 100,
    "max_depth": 10,
    "min_samples_leaf": 1,
    "random_state": 42,
}

# Prepare data for sklearn
X_train = train_pdf[feature_names].values
y_train = train_pdf['label'].values
X_test = test_pdf[feature_names].values
y_test = test_pdf['label'].values

with mlflow.start_run(run_name=f"sklearn_rf_iris_{datetime.now().strftime('%Y%m%d_%H%M%S')}"):
    # Train sklearn Random Forest
    print("Training sklearn Random Forest model...")
    model = RandomForestClassifier(
        n_estimators=hyperparams["n_estimators"],
        max_depth=hyperparams["max_depth"],
        min_samples_leaf=hyperparams["min_samples_leaf"],
        random_state=hyperparams["random_state"],
        n_jobs=-1
    )
    model.fit(X_train, y_train)
    print(f"Training completed! Number of trees: {model.n_estimators}")
    
    # Make predictions
    y_test_pred = model.predict(X_test)
    
    # Calculate metrics
    accuracy = accuracy_score(y_test, y_test_pred)
    precision = precision_score(y_test, y_test_pred, average='weighted')
    recall = recall_score(y_test, y_test_pred, average='weighted')
    f1 = f1_score(y_test, y_test_pred, average='weighted')
    
    # Log to MLflow
    mlflow.log_params(hyperparams)
    mlflow.log_param("training_framework", "sklearn")
    mlflow.log_param("data_processing", "spark")
    mlflow.log_metric("test_accuracy", accuracy)
    mlflow.log_metric("test_precision", precision)
    mlflow.log_metric("test_recall", recall)
    mlflow.log_metric("test_f1", f1)
    
    # Log sklearn model
    sample_input = pd.DataFrame([X_train[0]], columns=feature_names)
    sample_output = pd.DataFrame({"prediction": [0]})
    signature = infer_signature(sample_input, sample_output)
    
    mlflow.sklearn.log_model(
        sk_model=model,
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
stop_spark()
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

# Get details of the iris model
darwin mlflow model get --name IrisSklearnRFClassifier

# Get specific version details
darwin mlflow model get --name IrisSklearnRFClassifier --version 1
```

Expected output:
```
Model: IrisSklearnRFClassifier
Latest Version: 1
Description: Iris Sklearn RF Classifier
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
  --name iris-spark-classifier \
  --type api \
  --space ml-examples \
  --description "Iris Spark Random Forest Classifier"
```

---

## Step 12: Deploy the Model

Deploy the model using the MLflow model URI:

```bash
darwin serve deploy-model \
  --serve-name iris-spark-classifier \
  --artifact-version v1.0.0 \
  --model-uri models:/IrisSklearnRFClassifier/1 \
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
curl -X POST http://localhost/iris-spark-classifier/predict \
  -H "Content-Type: application/json" \
  -d @examples/iris-classification/sample-request.json
```

**Sample request payload:**

```json
{
  "features": {
    "sepal_length": 5.1,
    "sepal_width": 3.5,
    "petal_length": 1.4,
    "petal_width": 0.2
  }
}
```

**Expected response:**

```json
{
  "scores": [
    0
  ]
}
```

**Test with different iris samples:**

```bash
# Setosa sample (class 0)
curl -X POST http://localhost/iris-spark-classifier/predict \
  -H "Content-Type: application/json" \
  -d '{"features": {"sepal_length": 5.1, "sepal_width": 3.5, "petal_length": 1.4, "petal_width": 0.2}}'

# Versicolor sample (class 1)
curl -X POST http://localhost/iris-spark-classifier/predict \
  -H "Content-Type: application/json" \
  -d '{"features": {"sepal_length": 5.9, "sepal_width": 3.0, "petal_length": 4.2, "petal_width": 1.5}}'

# Virginica sample (class 2)
curl -X POST http://localhost/iris-spark-classifier/predict \
  -H "Content-Type: application/json" \
  -d '{"features": {"sepal_length": 6.7, "sepal_width": 3.0, "petal_length": 5.2, "petal_width": 2.3}}'
```

---

## Step 14: Undeploy the Serve Application

When done, undeploy the serve application:

```bash
darwin serve undeploy-model --serve-name iris-spark-classifier --env darwin-local
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
| 6 | Train model | Run notebook cells (Spark data processing + sklearn training) |
| 7 | Verify model | `darwin mlflow model get --name IrisSklearnRFClassifier` |
| 8 | Stop cluster | `darwin compute stop --cluster-id $CLUSTER_ID` |
| 9 | Configure serve auth | `darwin serve configure` |
| 10 | Create environment | `darwin serve environment create ...` |
| 11 | Create serve app | `darwin serve create --name iris-spark-classifier ...` |
| 12 | Deploy model | `darwin serve deploy-model ...` |
| 13 | Test inference | `curl -X POST .../predict` |
| 14 | Undeploy | `darwin serve undeploy-model ...` |

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
| `train_iris_model_spark.ipynb` | Hybrid training notebook (Spark + sklearn) |
| `train_iris_model.ipynb` | Pure sklearn version (no Spark) |
| `init-example.sh` | Quick setup script |
| `cluster-config.yaml` | Compute cluster configuration |
| `sample-request.json` | Sample inference request |
