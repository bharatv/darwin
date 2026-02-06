package status

import (
	"context"
	"fmt"

	rayv1 "github.com/ray-project/kuberay/ray-operator/apis/ray/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"

	computev1alpha1 "github.com/darwin/darwin-ray-operator/api/v1alpha1"
)

// Calculator calculates status for DarwinRayCluster
type Calculator struct {
	client    client.Client
	namespace string
}

// NewCalculator creates a new status calculator
func NewCalculator(c client.Client, namespace string) *Calculator {
	return &Calculator{
		client:    c,
		namespace: namespace,
	}
}

// CalculateStatus calculates the current status from pods and RayCluster state
func (c *Calculator) CalculateStatus(ctx context.Context, drc *computev1alpha1.DarwinRayCluster, rayCluster *rayv1.RayCluster) (*computev1alpha1.DarwinRayClusterStatus, error) {
	status := &computev1alpha1.DarwinRayClusterStatus{
		Phase:              drc.Status.Phase,
		RayClusterRef:      drc.Status.RayClusterRef,
		StartedAt:          drc.Status.StartedAt,
		ObservedGeneration: drc.Status.ObservedGeneration,
	}

	// Get pods for this cluster
	podList := &corev1.PodList{}
	labelSelector := client.MatchingLabels{
		"ray.io/cluster": rayCluster.Name,
	}
	if err := c.client.List(ctx, podList, client.InNamespace(c.namespace), labelSelector); err != nil {
		return nil, fmt.Errorf("failed to list pods: %w", err)
	}

	// Analyze pods
	var headPod *corev1.Pod
	var readyWorkers int32
	var totalMemoryGB int64
	activePods := int32(0)

	for i := range podList.Items {
		pod := &podList.Items[i]
		if pod.DeletionTimestamp != nil {
			continue
		}

		nodeType := pod.Labels["ray.io/node-type"]

		if nodeType == "head" {
			headPod = pod
		}

		if isPodReady(pod) {
			activePods++
			if nodeType == "worker" {
				readyWorkers++
			}

			// Calculate memory from resource requests
			for _, container := range pod.Spec.Containers {
				if mem := container.Resources.Requests.Memory(); mem != nil {
					totalMemoryGB += mem.Value() / (1024 * 1024 * 1024)
				}
			}
		}
	}

	status.ActivePods = activePods
	status.AvailableMemoryGB = totalMemoryGB
	status.ReadyWorkers = readyWorkers

	// Calculate desired workers
	desiredWorkers := int32(0)
	for _, wg := range drc.Spec.WorkerGroups {
		desiredWorkers += wg.Replicas
	}
	status.DesiredWorkers = desiredWorkers

	// Get head pod info
	if headPod != nil {
		status.HeadPodIP = headPod.Status.PodIP
		status.HeadServiceName = fmt.Sprintf("%s-head-svc", rayCluster.Name)

		// Build URLs
		if headPod.Status.PodIP != "" {
			status.RayDashboardURL = fmt.Sprintf("http://%s:8265", headPod.Status.PodIP)
			if drc.Spec.HeadNode.EnableJupyter {
				status.JupyterURL = fmt.Sprintf("http://%s:8888", headPod.Status.PodIP)
			}
		}
	}

	// Determine phase based on pod states
	status.Phase = c.determinePhase(drc, headPod, readyWorkers, desiredWorkers, podList)

	// Set conditions
	status.Conditions = c.buildConditions(drc, headPod, readyWorkers, desiredWorkers)

	// Set message based on phase
	status.Message = c.getPhaseMessage(status.Phase, readyWorkers, desiredWorkers)

	return status, nil
}

// determinePhase determines the cluster phase from pod states
func (c *Calculator) determinePhase(drc *computev1alpha1.DarwinRayCluster, headPod *corev1.Pod, readyWorkers, desiredWorkers int32, podList *corev1.PodList) computev1alpha1.ClusterPhase {
	// Check for failed pods
	for i := range podList.Items {
		pod := &podList.Items[i]
		if pod.Status.Phase == corev1.PodFailed {
			return computev1alpha1.PhaseFailed
		}
		// Check for CrashLoopBackOff
		for _, cs := range pod.Status.ContainerStatuses {
			if cs.State.Waiting != nil && cs.State.Waiting.Reason == "CrashLoopBackOff" {
				return computev1alpha1.PhaseFailed
			}
		}
	}

	// No head pod yet
	if headPod == nil {
		return computev1alpha1.PhaseCreating
	}

	// Head pod not ready
	if !isPodReady(headPod) {
		return computev1alpha1.PhaseCreating
	}

	// Head pod is ready
	// Check if Jupyter is enabled and ready
	if drc.Spec.HeadNode.EnableJupyter {
		if !isJupyterReady(headPod) {
			return computev1alpha1.PhaseHeadNodeUp
		}
		// Jupyter is ready, check workers
		if desiredWorkers == 0 || readyWorkers >= desiredWorkers {
			return computev1alpha1.PhaseActive
		}
		return computev1alpha1.PhaseJupyterUp
	}

	// No Jupyter, check workers
	if desiredWorkers == 0 || readyWorkers >= desiredWorkers {
		return computev1alpha1.PhaseActive
	}

	return computev1alpha1.PhaseHeadNodeUp
}

// buildConditions builds the status conditions
func (c *Calculator) buildConditions(drc *computev1alpha1.DarwinRayCluster, headPod *corev1.Pod, readyWorkers, desiredWorkers int32) []metav1.Condition {
	conditions := []metav1.Condition{}

	// RayCluster created condition
	conditions = append(conditions, metav1.Condition{
		Type:               computev1alpha1.ConditionTypeRayClusterCreated,
		Status:             metav1.ConditionTrue,
		Reason:             computev1alpha1.ReasonRayClusterCreated,
		Message:            "RayCluster CR exists",
		LastTransitionTime: metav1.Now(),
		ObservedGeneration: drc.Generation,
	})

	// Head node ready condition
	headReady := metav1.ConditionFalse
	headMessage := "Head node is not ready"
	if headPod != nil && isPodReady(headPod) {
		headReady = metav1.ConditionTrue
		headMessage = "Head node is ready"
	}
	conditions = append(conditions, metav1.Condition{
		Type:               computev1alpha1.ConditionTypeHeadNodeReady,
		Status:             headReady,
		Reason:             string(headReady),
		Message:            headMessage,
		LastTransitionTime: metav1.Now(),
		ObservedGeneration: drc.Generation,
	})

	// Workers ready condition
	workersReady := metav1.ConditionFalse
	workersMessage := fmt.Sprintf("Workers ready: %d/%d", readyWorkers, desiredWorkers)
	if desiredWorkers == 0 || readyWorkers >= desiredWorkers {
		workersReady = metav1.ConditionTrue
	}
	conditions = append(conditions, metav1.Condition{
		Type:               computev1alpha1.ConditionTypeWorkersReady,
		Status:             workersReady,
		Reason:             string(workersReady),
		Message:            workersMessage,
		LastTransitionTime: metav1.Now(),
		ObservedGeneration: drc.Generation,
	})

	// Jupyter ready condition (if enabled)
	if drc.Spec.HeadNode.EnableJupyter {
		jupyterReady := metav1.ConditionFalse
		jupyterMessage := "Jupyter is not ready"
		if headPod != nil && isJupyterReady(headPod) {
			jupyterReady = metav1.ConditionTrue
			jupyterMessage = "Jupyter is ready"
		}
		conditions = append(conditions, metav1.Condition{
			Type:               computev1alpha1.ConditionTypeJupyterReady,
			Status:             jupyterReady,
			Reason:             string(jupyterReady),
			Message:            jupyterMessage,
			LastTransitionTime: metav1.Now(),
			ObservedGeneration: drc.Generation,
		})
	}

	// Overall ready condition
	overallReady := metav1.ConditionFalse
	overallMessage := "Cluster is not ready"
	if headReady == metav1.ConditionTrue && workersReady == metav1.ConditionTrue {
		overallReady = metav1.ConditionTrue
		overallMessage = "Cluster is ready"
	}
	conditions = append(conditions, metav1.Condition{
		Type:               computev1alpha1.ConditionTypeReady,
		Status:             overallReady,
		Reason:             string(overallReady),
		Message:            overallMessage,
		LastTransitionTime: metav1.Now(),
		ObservedGeneration: drc.Generation,
	})

	return conditions
}

// getPhaseMessage returns a human-readable message for the phase
func (c *Calculator) getPhaseMessage(phase computev1alpha1.ClusterPhase, readyWorkers, desiredWorkers int32) string {
	switch phase {
	case computev1alpha1.PhaseInactive:
		return "Cluster is inactive"
	case computev1alpha1.PhaseCreating:
		return "Creating cluster resources"
	case computev1alpha1.PhaseHeadNodeUp:
		return "Head node is up, waiting for workers"
	case computev1alpha1.PhaseJupyterUp:
		return fmt.Sprintf("Jupyter is ready, workers: %d/%d", readyWorkers, desiredWorkers)
	case computev1alpha1.PhaseActive:
		return fmt.Sprintf("Cluster is active with %d workers", readyWorkers)
	case computev1alpha1.PhaseFailed:
		return "Cluster has failed"
	case computev1alpha1.PhaseTerminating:
		return "Cluster is terminating"
	default:
		return "Unknown state"
	}
}

// isPodReady checks if a pod is ready
func isPodReady(pod *corev1.Pod) bool {
	if pod.Status.Phase != corev1.PodRunning {
		return false
	}
	for _, condition := range pod.Status.Conditions {
		if condition.Type == corev1.PodReady && condition.Status == corev1.ConditionTrue {
			return true
		}
	}
	return false
}

// isJupyterReady checks if Jupyter is ready on the head pod
// This is a simplified check - in production, you might want to actually probe the Jupyter endpoint
func isJupyterReady(pod *corev1.Pod) bool {
	if !isPodReady(pod) {
		return false
	}
	// Check if the container with Jupyter port is ready
	for _, cs := range pod.Status.ContainerStatuses {
		if cs.Name == "ray-head" && cs.Ready {
			return true
		}
	}
	return false
}
