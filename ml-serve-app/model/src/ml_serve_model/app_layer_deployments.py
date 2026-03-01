from tortoise import models, fields


class AppLayerDeployment(models.Model):
    id = fields.IntField(pk=True)

    # Link to the parent deployment row
    deployment = fields.OneToOneField(
        "models.Deployment",
        related_name="app_layer_deployments",
        on_delete=fields.CASCADE
    )

    deployment_strategy = fields.CharField(max_length=50, null=True)  # e.g., "ROLLING", "CANARY"
    deployment_params = fields.JSONField(null=True)  # Flexible for any strategy-specific params
    environment_variables = fields.JSONField(null=True)  # Environment variables

    # Deployment orchestration phase tracking (nullable for backward compatibility)
    phase = fields.CharField(max_length=50, null=True)
    phase_metadata = fields.JSONField(null=True)
    requires_approval = fields.BooleanField(null=True)

    class Meta:
        table = "app_layer_deployments"
