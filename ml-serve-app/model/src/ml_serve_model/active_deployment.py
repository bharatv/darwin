from tortoise import models, fields


class ActiveDeployment(models.Model):
    """
    Active Deployment model to store active deployments
    """
    id = fields.IntField(pk=True)

    deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="active_deployments",
        on_delete=fields.CASCADE
    )

    previous_deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="previous_active_deployments",
        on_delete=fields.SET_NULL,
        null=True
    )

    # Candidate deployment during transition phases (canary/blue-green/rolling)
    candidate_deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="candidate_active_deployments",
        on_delete=fields.SET_NULL,
        null=True,
    )

    environment = fields.ForeignKeyField(
        "models.Environment",
        related_name="deployments",
        on_delete=fields.CASCADE
    )

    serve = fields.ForeignKeyField(
        "models.Serve",
        related_name="active_deployments",
        on_delete=fields.CASCADE
    )

    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "active_deployments"
