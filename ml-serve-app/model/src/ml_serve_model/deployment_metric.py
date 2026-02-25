"""Deployment metric model for metrics collection."""
from tortoise import models, fields


class DeploymentMetric(models.Model):
    """
    Stores deployment metrics (request rate, error rate, latency, CPU, memory).
    1-min frequency, 5-day retention.
    """
    id = fields.IntField(pk=True)
    deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="deployment_metrics",
        on_delete=fields.CASCADE,
    )
    timestamp = fields.DatetimeField()
    metric_name = fields.CharField(max_length=64)
    value = fields.FloatField()
    labels = fields.JSONField(null=True)

    class Meta:
        table = "deployment_metrics"
