"""Deployment lock model for canary deployment locking."""
from tortoise import models, fields


class DeploymentLock(models.Model):
    """
    Lock to prevent concurrent deployments when canary is in progress.
    One lock per (serve_id, environment_id).
    """
    id = fields.IntField(pk=True)
    serve = fields.ForeignKeyField(
        "models.Serve",
        related_name="deployment_locks",
        on_delete=fields.CASCADE,
    )
    environment = fields.ForeignKeyField(
        "models.Environment",
        related_name="deployment_locks",
        on_delete=fields.CASCADE,
    )
    deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="deployment_locks",
        on_delete=fields.SET_NULL,
        null=True,
    )
    locked_at = fields.DatetimeField()
    locked_by = fields.ForeignKeyField(
        "models.User",
        related_name="deployment_locks",
        on_delete=fields.SET_NULL,
        null=True,
    )

    class Meta:
        table = "deployment_locks"
        unique_together = (("serve", "environment"),)
