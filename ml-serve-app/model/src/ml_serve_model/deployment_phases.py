from tortoise import models, fields


class DeploymentPhase(models.Model):
    id = fields.IntField(pk=True)

    deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="phases",
        on_delete=fields.CASCADE,
    )

    phase_name = fields.CharField(max_length=50)
    traffic_weights = fields.JSONField(null=True)

    approver_username = fields.CharField(max_length=255, null=True)
    approved_at = fields.DatetimeField(null=True)

    rejection_reason = fields.TextField(null=True)
    notes = fields.TextField(null=True)

    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "deployment_phases"

