package controller

import (
	"context"
	"fmt"
	"time"

	"github.com/go-logr/logr"
	rayv1 "github.com/ray-project/kuberay/ray-operator/apis/ray/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	computev1alpha1 "github.com/darwin/darwin-ray-operator/api/v1alpha1"
	"github.com/darwin/darwin-ray-operator/internal/raycluster"
	"github.com/darwin/darwin-ray-operator/internal/status"
)

const (
	// FinalizerName is the finalizer for DarwinRayCluster
	FinalizerName = "compute.darwin.io/finalizer"
	// RequeueInterval is the default requeue interval
	RequeueInterval = 10 * time.Second
	// StatusUpdateInterval is how often to requeue for status updates
	StatusUpdateInterval = 30 * time.Second
)

// DarwinRayClusterReconciler reconciles a DarwinRayCluster object
type DarwinRayClusterReconciler struct {
	client.Client
	Scheme       *runtime.Scheme
	Recorder     record.EventRecorder
	RayNamespace string
}

// +kubebuilder:rbac:groups=compute.darwin.io,resources=darwinrayclusters,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=compute.darwin.io,resources=darwinrayclusters/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=compute.darwin.io,resources=darwinrayclusters/finalizers,verbs=update
// +kubebuilder:rbac:groups=ray.io,resources=rayclusters,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=ray.io,resources=rayclusters/status,verbs=get
// +kubebuilder:rbac:groups="",resources=pods,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch

// Reconcile is the main reconciliation loop for DarwinRayCluster
func (r *DarwinRayClusterReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("Reconciling DarwinRayCluster", "namespace", req.Namespace, "name", req.Name)

	// Fetch the DarwinRayCluster instance
	drc := &computev1alpha1.DarwinRayCluster{}
	if err := r.Get(ctx, req.NamespacedName, drc); err != nil {
		if errors.IsNotFound(err) {
			logger.Info("DarwinRayCluster not found, ignoring")
			return ctrl.Result{}, nil
		}
		logger.Error(err, "Failed to get DarwinRayCluster")
		return ctrl.Result{}, err
	}

	// Handle deletion
	if !drc.DeletionTimestamp.IsZero() {
		return r.handleDeletion(ctx, logger, drc)
	}

	// Add finalizer if not present
	if !controllerutil.ContainsFinalizer(drc, FinalizerName) {
		controllerutil.AddFinalizer(drc, FinalizerName)
		if err := r.Update(ctx, drc); err != nil {
			logger.Error(err, "Failed to add finalizer")
			return ctrl.Result{}, err
		}
		return ctrl.Result{Requeue: true}, nil
	}

	// Handle suspended state
	if drc.Spec.Suspend {
		return r.handleSuspend(ctx, logger, drc)
	}

	// Main reconciliation logic
	return r.reconcileCluster(ctx, logger, drc)
}

// handleDeletion handles the deletion of DarwinRayCluster
func (r *DarwinRayClusterReconciler) handleDeletion(ctx context.Context, logger logr.Logger, drc *computev1alpha1.DarwinRayCluster) (ctrl.Result, error) {
	logger.Info("Handling deletion of DarwinRayCluster")

	// Update phase to Terminating
	if drc.Status.Phase != computev1alpha1.PhaseTerminating {
		drc.Status.Phase = computev1alpha1.PhaseTerminating
		drc.Status.Message = "Cluster is being terminated"
		if err := r.Status().Update(ctx, drc); err != nil {
			logger.Error(err, "Failed to update status to Terminating")
			return ctrl.Result{}, err
		}
		r.Recorder.Event(drc, corev1.EventTypeNormal, "Terminating", "Cluster termination started")
	}

	// Delete the underlying RayCluster if it exists
	if drc.Status.RayClusterRef != "" {
		rayCluster := &rayv1.RayCluster{}
		rayClusterName := types.NamespacedName{
			Namespace: r.RayNamespace,
			Name:      drc.Status.RayClusterRef,
		}
		if err := r.Get(ctx, rayClusterName, rayCluster); err == nil {
			logger.Info("Deleting underlying RayCluster", "name", drc.Status.RayClusterRef)
			if err := r.Delete(ctx, rayCluster); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "Failed to delete RayCluster")
				return ctrl.Result{}, err
			}
			// Requeue to wait for RayCluster deletion
			return ctrl.Result{RequeueAfter: RequeueInterval}, nil
		} else if !errors.IsNotFound(err) {
			logger.Error(err, "Failed to get RayCluster for deletion")
			return ctrl.Result{}, err
		}
	}

	// Remove finalizer
	controllerutil.RemoveFinalizer(drc, FinalizerName)
	if err := r.Update(ctx, drc); err != nil {
		logger.Error(err, "Failed to remove finalizer")
		return ctrl.Result{}, err
	}

	logger.Info("Successfully deleted DarwinRayCluster")
	return ctrl.Result{}, nil
}

// handleSuspend handles the suspended state (cluster stop)
func (r *DarwinRayClusterReconciler) handleSuspend(ctx context.Context, logger logr.Logger, drc *computev1alpha1.DarwinRayCluster) (ctrl.Result, error) {
	logger.Info("Handling suspended DarwinRayCluster")

	// Delete the underlying RayCluster if it exists
	if drc.Status.RayClusterRef != "" {
		rayCluster := &rayv1.RayCluster{}
		rayClusterName := types.NamespacedName{
			Namespace: r.RayNamespace,
			Name:      drc.Status.RayClusterRef,
		}
		if err := r.Get(ctx, rayClusterName, rayCluster); err == nil {
			logger.Info("Deleting RayCluster for suspended state", "name", drc.Status.RayClusterRef)
			if err := r.Delete(ctx, rayCluster); err != nil && !errors.IsNotFound(err) {
				logger.Error(err, "Failed to delete RayCluster")
				return ctrl.Result{}, err
			}
			return ctrl.Result{RequeueAfter: RequeueInterval}, nil
		} else if !errors.IsNotFound(err) {
			return ctrl.Result{}, err
		}
	}

	// Update status to Inactive
	if drc.Status.Phase != computev1alpha1.PhaseInactive {
		drc.Status.Phase = computev1alpha1.PhaseInactive
		drc.Status.ActivePods = 0
		drc.Status.AvailableMemoryGB = 0
		drc.Status.ReadyWorkers = 0
		drc.Status.HeadPodIP = ""
		drc.Status.JupyterURL = ""
		drc.Status.RayDashboardURL = ""
		drc.Status.RayClusterRef = ""
		drc.Status.Message = "Cluster is suspended"
		drc.Status.LastTransitionTime = metav1.Now()
		r.setCondition(drc, computev1alpha1.ConditionTypeReady, metav1.ConditionFalse, computev1alpha1.ReasonSuspended, "Cluster is suspended")

		if err := r.Status().Update(ctx, drc); err != nil {
			logger.Error(err, "Failed to update status to Inactive")
			return ctrl.Result{}, err
		}
		r.Recorder.Event(drc, corev1.EventTypeNormal, "Suspended", "Cluster suspended successfully")
	}

	return ctrl.Result{}, nil
}

// reconcileCluster is the main reconciliation logic for active clusters
func (r *DarwinRayClusterReconciler) reconcileCluster(ctx context.Context, logger logr.Logger, drc *computev1alpha1.DarwinRayCluster) (ctrl.Result, error) {
	// Generate RayCluster name
	rayClusterName := fmt.Sprintf("%s-kuberay", drc.Name)

	// Check if RayCluster exists
	rayCluster := &rayv1.RayCluster{}
	rayClusterNamespacedName := types.NamespacedName{
		Namespace: r.RayNamespace,
		Name:      rayClusterName,
	}

	rayClusterExists := true
	if err := r.Get(ctx, rayClusterNamespacedName, rayCluster); err != nil {
		if errors.IsNotFound(err) {
			rayClusterExists = false
		} else {
			logger.Error(err, "Failed to get RayCluster")
			return ctrl.Result{}, err
		}
	}

	// Create RayCluster if it doesn't exist
	if !rayClusterExists {
		return r.createRayCluster(ctx, logger, drc, rayClusterName)
	}

	// Update RayCluster if spec changed
	if drc.Generation != drc.Status.ObservedGeneration {
		return r.updateRayCluster(ctx, logger, drc, rayCluster)
	}

	// Calculate and update status from current state
	return r.updateStatus(ctx, logger, drc, rayCluster)
}

// createRayCluster creates a new RayCluster CR
func (r *DarwinRayClusterReconciler) createRayCluster(ctx context.Context, logger logr.Logger, drc *computev1alpha1.DarwinRayCluster, rayClusterName string) (ctrl.Result, error) {
	logger.Info("Creating RayCluster", "name", rayClusterName)

	// Update phase to Creating
	drc.Status.Phase = computev1alpha1.PhaseCreating
	drc.Status.Message = "Creating RayCluster"
	drc.Status.LastTransitionTime = metav1.Now()
	now := metav1.Now()
	drc.Status.StartedAt = &now
	r.setCondition(drc, computev1alpha1.ConditionTypeRayClusterCreated, metav1.ConditionFalse, computev1alpha1.ReasonCreating, "RayCluster is being created")

	if err := r.Status().Update(ctx, drc); err != nil {
		logger.Error(err, "Failed to update status to Creating")
		return ctrl.Result{}, err
	}

	// Build RayCluster spec
	rayCluster, err := raycluster.BuildRayCluster(drc, rayClusterName, r.RayNamespace)
	if err != nil {
		logger.Error(err, "Failed to build RayCluster spec")
		drc.Status.Phase = computev1alpha1.PhaseFailed
		drc.Status.Message = fmt.Sprintf("Failed to build RayCluster: %v", err)
		r.setCondition(drc, computev1alpha1.ConditionTypeReady, metav1.ConditionFalse, computev1alpha1.ReasonFailed, drc.Status.Message)
		_ = r.Status().Update(ctx, drc)
		r.Recorder.Event(drc, corev1.EventTypeWarning, "Failed", drc.Status.Message)
		return ctrl.Result{}, err
	}

	// Set owner reference
	if err := controllerutil.SetControllerReference(drc, rayCluster, r.Scheme); err != nil {
		logger.Error(err, "Failed to set owner reference")
		return ctrl.Result{}, err
	}

	// Create the RayCluster
	if err := r.Create(ctx, rayCluster); err != nil {
		logger.Error(err, "Failed to create RayCluster")
		drc.Status.Phase = computev1alpha1.PhaseFailed
		drc.Status.Message = fmt.Sprintf("Failed to create RayCluster: %v", err)
		r.setCondition(drc, computev1alpha1.ConditionTypeReady, metav1.ConditionFalse, computev1alpha1.ReasonFailed, drc.Status.Message)
		_ = r.Status().Update(ctx, drc)
		r.Recorder.Event(drc, corev1.EventTypeWarning, "Failed", drc.Status.Message)
		return ctrl.Result{}, err
	}

	// Update status with RayCluster reference
	drc.Status.RayClusterRef = rayClusterName
	drc.Status.ObservedGeneration = drc.Generation
	r.setCondition(drc, computev1alpha1.ConditionTypeRayClusterCreated, metav1.ConditionTrue, computev1alpha1.ReasonRayClusterCreated, "RayCluster created successfully")

	if err := r.Status().Update(ctx, drc); err != nil {
		logger.Error(err, "Failed to update status with RayCluster reference")
		return ctrl.Result{}, err
	}

	r.Recorder.Event(drc, corev1.EventTypeNormal, "Created", fmt.Sprintf("RayCluster %s created", rayClusterName))
	logger.Info("Successfully created RayCluster", "name", rayClusterName)

	return ctrl.Result{RequeueAfter: RequeueInterval}, nil
}

// updateRayCluster updates an existing RayCluster CR
func (r *DarwinRayClusterReconciler) updateRayCluster(ctx context.Context, logger logr.Logger, drc *computev1alpha1.DarwinRayCluster, rayCluster *rayv1.RayCluster) (ctrl.Result, error) {
	logger.Info("Updating RayCluster", "name", rayCluster.Name)

	// Build updated RayCluster spec
	updatedRayCluster, err := raycluster.BuildRayCluster(drc, rayCluster.Name, r.RayNamespace)
	if err != nil {
		logger.Error(err, "Failed to build updated RayCluster spec")
		return ctrl.Result{}, err
	}

	// Update the spec
	rayCluster.Spec = updatedRayCluster.Spec

	if err := r.Update(ctx, rayCluster); err != nil {
		logger.Error(err, "Failed to update RayCluster")
		return ctrl.Result{}, err
	}

	// Update observed generation
	drc.Status.ObservedGeneration = drc.Generation
	if err := r.Status().Update(ctx, drc); err != nil {
		logger.Error(err, "Failed to update observed generation")
		return ctrl.Result{}, err
	}

	r.Recorder.Event(drc, corev1.EventTypeNormal, "Updated", fmt.Sprintf("RayCluster %s updated", rayCluster.Name))
	logger.Info("Successfully updated RayCluster", "name", rayCluster.Name)

	return ctrl.Result{RequeueAfter: RequeueInterval}, nil
}

// updateStatus calculates and updates the DarwinRayCluster status
func (r *DarwinRayClusterReconciler) updateStatus(ctx context.Context, logger logr.Logger, drc *computev1alpha1.DarwinRayCluster, rayCluster *rayv1.RayCluster) (ctrl.Result, error) {
	// Calculate status from pods
	calculator := status.NewCalculator(r.Client, r.RayNamespace)
	newStatus, err := calculator.CalculateStatus(ctx, drc, rayCluster)
	if err != nil {
		logger.Error(err, "Failed to calculate status")
		return ctrl.Result{}, err
	}

	// Check if status changed
	statusChanged := r.hasStatusChanged(drc, newStatus)

	if statusChanged {
		oldPhase := drc.Status.Phase

		// Update status fields
		drc.Status.Phase = newStatus.Phase
		drc.Status.ActivePods = newStatus.ActivePods
		drc.Status.AvailableMemoryGB = newStatus.AvailableMemoryGB
		drc.Status.HeadPodIP = newStatus.HeadPodIP
		drc.Status.HeadServiceName = newStatus.HeadServiceName
		drc.Status.JupyterURL = newStatus.JupyterURL
		drc.Status.RayDashboardURL = newStatus.RayDashboardURL
		drc.Status.ReadyWorkers = newStatus.ReadyWorkers
		drc.Status.DesiredWorkers = newStatus.DesiredWorkers
		drc.Status.Message = newStatus.Message
		drc.Status.Conditions = newStatus.Conditions

		if oldPhase != newStatus.Phase {
			drc.Status.LastTransitionTime = metav1.Now()
			logger.Info("Phase transitioned", "from", oldPhase, "to", newStatus.Phase)
			r.Recorder.Event(drc, corev1.EventTypeNormal, "PhaseChanged", fmt.Sprintf("Phase changed from %s to %s", oldPhase, newStatus.Phase))
		}

		if err := r.Status().Update(ctx, drc); err != nil {
			logger.Error(err, "Failed to update status")
			return ctrl.Result{}, err
		}
	}

	// Check auto-termination
	if result, terminate := r.checkAutoTermination(ctx, logger, drc); terminate {
		return result, nil
	}

	// Requeue for periodic status updates
	return ctrl.Result{RequeueAfter: StatusUpdateInterval}, nil
}

// hasStatusChanged checks if the status has meaningfully changed
func (r *DarwinRayClusterReconciler) hasStatusChanged(drc *computev1alpha1.DarwinRayCluster, newStatus *computev1alpha1.DarwinRayClusterStatus) bool {
	return drc.Status.Phase != newStatus.Phase ||
		drc.Status.ActivePods != newStatus.ActivePods ||
		drc.Status.ReadyWorkers != newStatus.ReadyWorkers ||
		drc.Status.HeadPodIP != newStatus.HeadPodIP
}

// checkAutoTermination checks if the cluster should be auto-terminated
func (r *DarwinRayClusterReconciler) checkAutoTermination(ctx context.Context, logger logr.Logger, drc *computev1alpha1.DarwinRayCluster) (ctrl.Result, bool) {
	if drc.Spec.AutoTermination == nil || !drc.Spec.AutoTermination.Enabled {
		return ctrl.Result{}, false
	}

	// Check max runtime
	if drc.Spec.AutoTermination.MaxRuntimeMinutes > 0 && drc.Status.StartedAt != nil {
		maxDuration := time.Duration(drc.Spec.AutoTermination.MaxRuntimeMinutes) * time.Minute
		if time.Since(drc.Status.StartedAt.Time) > maxDuration {
			logger.Info("Auto-terminating cluster due to max runtime exceeded")
			drc.Spec.Suspend = true
			if err := r.Update(ctx, drc); err != nil {
				logger.Error(err, "Failed to suspend cluster for auto-termination")
				return ctrl.Result{}, false
			}
			r.Recorder.Event(drc, corev1.EventTypeNormal, "AutoTerminated", "Cluster auto-terminated due to max runtime exceeded")
			return ctrl.Result{Requeue: true}, true
		}
	}

	// TODO: Implement idle timeout detection (requires tracking last activity)

	return ctrl.Result{}, false
}

// setCondition sets a condition on the DarwinRayCluster
func (r *DarwinRayClusterReconciler) setCondition(drc *computev1alpha1.DarwinRayCluster, conditionType string, status metav1.ConditionStatus, reason, message string) {
	condition := metav1.Condition{
		Type:               conditionType,
		Status:             status,
		Reason:             reason,
		Message:            message,
		LastTransitionTime: metav1.Now(),
		ObservedGeneration: drc.Generation,
	}

	// Find and update existing condition or append new one
	found := false
	for i, c := range drc.Status.Conditions {
		if c.Type == conditionType {
			if c.Status != status || c.Reason != reason || c.Message != message {
				drc.Status.Conditions[i] = condition
			}
			found = true
			break
		}
	}
	if !found {
		drc.Status.Conditions = append(drc.Status.Conditions, condition)
	}
}

// SetupWithManager sets up the controller with the Manager.
func (r *DarwinRayClusterReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&computev1alpha1.DarwinRayCluster{}).
		Owns(&rayv1.RayCluster{}).
		Complete(r)
}
