from tortoise import models, fields
from tortoise.validators import Validator
from tortoise.exceptions import ValidationError

from ml_serve_model.enums import DeploymentStrategy


class DeploymentStrategyValidator(Validator):
    """Validates deployment_strategy is one of rolling, canary, blue-green when set."""

    def __call__(self, value):
        if value is None:
            return
        allowed = {s.value for s in DeploymentStrategy}
        if value not in allowed:
            raise ValidationError(
                f"deployment_strategy must be one of {sorted(allowed)}, got '{value}'"
            )


class AppLayerDeployment(models.Model):
    id = fields.IntField(pk=True)

    # Link to the parent deployment row
    deployment = fields.OneToOneField(
        "models.Deployment",
        related_name="app_layer_deployments",
        on_delete=fields.CASCADE
    )

    deployment_strategy = fields.CharField(
        max_length=50,
        null=True,
        validators=[DeploymentStrategyValidator()],
    )
    deployment_params = fields.JSONField(null=True)  # Flexible for any strategy-specific params
    environment_variables = fields.JSONField(null=True)  # Environment variables

    class Meta:
        table = "app_layer_deployments"
