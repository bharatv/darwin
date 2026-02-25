from tortoise import models, fields
from .enums import DeploymentStrategy


class AppLayerDeployment(models.Model):
    id = fields.IntField(pk=True)

    # Link to the parent deployment row
    deployment = fields.OneToOneField(
        "models.Deployment",
        related_name="app_layer_deployments",
        on_delete=fields.CASCADE
    )

    # Strategy field now references DeploymentStrategy enum values
    # Defaults to IMMEDIATE for backward compatibility
    deployment_strategy = fields.CharField(max_length=50, null=True, default="IMMEDIATE")
    deployment_params = fields.JSONField(null=True)  # Flexible for any strategy-specific params
    environment_variables = fields.JSONField(null=True)  # Environment variables

    class Meta:
        table = "app_layer_deployments"
