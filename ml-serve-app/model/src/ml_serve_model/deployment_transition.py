from tortoise import models, fields


class DeploymentTransition(models.Model):
    """
    Tracks deployment state transitions for promotion/rollback operations.
    """
    id = fields.IntField(pk=True)

    # Link to the deployment being transitioned
    deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="transitions",
        on_delete=fields.CASCADE
    )

    # Transition metadata
    from_status = fields.CharField(max_length=50, null=True)
    to_status = fields.CharField(max_length=50)
    transition_type = fields.CharField(max_length=50)  # e.g., "PROMOTE", "ROLLBACK", "DEPLOY"
    
    # Operator and timing
    triggered_by = fields.CharField(max_length=255, null=True)  # User or system
    triggered_at = fields.DatetimeField(auto_now_add=True)
    
    # Additional context
    reason = fields.TextField(null=True)
    metadata = fields.JSONField(null=True)  # Flexible for strategy-specific data

    class Meta:
        table = "deployment_transitions"
        ordering = ["-triggered_at"]
