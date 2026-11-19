"""Optional one-time setup: create an MLflow experiment with traces in Unity Catalog.

Run this once (e.g. in a notebook or with
`python setup/create_uc_backed_experiment.py`). To send the agent's traces there, put
the printed experiment ID in databricks.yml under the sru_syntax_agent app's
`app-experiment` resource (replacing the bundle-managed experiment).
"""

import os

import mlflow
from mlflow.entities.trace_location import UnityCatalog

# SQL warehouse used to write/read traces in Unity Catalog (Serverless Starter
# Warehouse)
os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = os.getenv(
    "MLFLOW_TRACING_SQL_WAREHOUSE_ID", "50d2bd4ddf65e0f5"
)

mlflow.set_tracking_uri("databricks")

experiment = mlflow.set_experiment(
    experiment_name="/Users/amanda.xu@usda.gov/sru-syntax-agent-uc-experiment",
    trace_location=UnityCatalog(
        catalog_name="users",
        schema_name="amanda_xu",
        table_prefix="sru_syntax_agent",
    ),
)
print(f"Experiment ID: {experiment.experiment_id}")
