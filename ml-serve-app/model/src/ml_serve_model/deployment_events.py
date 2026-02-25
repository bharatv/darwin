from tortoise import models, fields


class DeploymentEvent(models.Model):
    """
    Deployment Event model to track deployment lifecycle events.
    
    Used to track canary progression, promotions, rollbacks, and other
    deployment-related activities for observability and auditing.
    """
    id = fields.IntField(pk=True)

    deployment = fields.ForeignKeyField(
        "models.Deployment",
        related_name="deployment_events",
        on_delete=fields.CASCADE
    )

    event_type = fields.CharField(max_length=50)  # e.g., "canary_initialized", "traffic_weight_changed", "promotion_requested"
    event_data = fields.JSONField(null=True)  # Flexible storage for event-specific data
    
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "deployment_events"
