package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ClusterPhase represents the current phase of the DarwinRayCluster
// +kubebuilder:validation:Enum=Inactive;Creating;HeadNodeUp;JupyterUp;Active;Failed;Terminating
type ClusterPhase string

const (
	// PhaseInactive indicates the cluster is not running
	PhaseInactive ClusterPhase = "Inactive"
	// PhaseCreating indicates the cluster is being created
	PhaseCreating ClusterPhase = "Creating"
	// PhaseHeadNodeUp indicates the head node is up and running
	PhaseHeadNodeUp ClusterPhase = "HeadNodeUp"
	// PhaseJupyterUp indicates Jupyter is ready on the head node
	PhaseJupyterUp ClusterPhase = "JupyterUp"
	// PhaseActive indicates the cluster is fully active with workers
	PhaseActive ClusterPhase = "Active"
	// PhaseFailed indicates the cluster has failed
	PhaseFailed ClusterPhase = "Failed"
	// PhaseTerminating indicates the cluster is being terminated
	PhaseTerminating ClusterPhase = "Terminating"
)

// ResourceSpec defines CPU and memory resources
type ResourceSpec struct {
	// CPU cores requested
	// +kubebuilder:validation:Pattern=`^[0-9]+(\.[0-9]+)?$`
	CPU string `json:"cpu"`
	// Memory in GB
	// +kubebuilder:validation:Minimum=1
	MemoryGB int32 `json:"memoryGB"`
	// GPU count (optional)
	// +optional
	GPU int32 `json:"gpu,omitempty"`
	// GPU type (e.g., "nvidia.com/gpu")
	// +optional
	GPUType string `json:"gpuType,omitempty"`
}

// VolumeMount defines a volume mount configuration
type VolumeMount struct {
	// Name of the volume
	Name string `json:"name"`
	// Mount path inside the container
	MountPath string `json:"mountPath"`
	// PVC name to mount
	// +optional
	PVCName string `json:"pvcName,omitempty"`
	// ConfigMap name to mount
	// +optional
	ConfigMapName string `json:"configMapName,omitempty"`
	// Secret name to mount
	// +optional
	SecretName string `json:"secretName,omitempty"`
	// Read-only mount
	// +optional
	ReadOnly bool `json:"readOnly,omitempty"`
}

// HeadNodeSpec defines the head node configuration
type HeadNodeSpec struct {
	// Resources for the head node
	Resources ResourceSpec `json:"resources"`
	// Service account name
	// +optional
	ServiceAccountName string `json:"serviceAccountName,omitempty"`
	// Volume mounts
	// +optional
	VolumeMounts []VolumeMount `json:"volumeMounts,omitempty"`
	// Environment variables
	// +optional
	Env []corev1.EnvVar `json:"env,omitempty"`
	// Ray start parameters for head node
	// +optional
	RayStartParams map[string]string `json:"rayStartParams,omitempty"`
	// Node selector
	// +optional
	NodeSelector map[string]string `json:"nodeSelector,omitempty"`
	// Tolerations
	// +optional
	Tolerations []corev1.Toleration `json:"tolerations,omitempty"`
	// Annotations for the head pod
	// +optional
	Annotations map[string]string `json:"annotations,omitempty"`
	// Enable Jupyter notebook
	// +optional
	EnableJupyter bool `json:"enableJupyter,omitempty"`
}

// WorkerGroupSpec defines a worker group configuration
type WorkerGroupSpec struct {
	// Name of the worker group
	Name string `json:"name"`
	// Number of replicas
	// +kubebuilder:validation:Minimum=0
	Replicas int32 `json:"replicas"`
	// Minimum replicas for autoscaling
	// +optional
	// +kubebuilder:validation:Minimum=0
	MinReplicas int32 `json:"minReplicas,omitempty"`
	// Maximum replicas for autoscaling
	// +optional
	MaxReplicas int32 `json:"maxReplicas,omitempty"`
	// Resources for workers in this group
	Resources ResourceSpec `json:"resources"`
	// Service account name
	// +optional
	ServiceAccountName string `json:"serviceAccountName,omitempty"`
	// Volume mounts
	// +optional
	VolumeMounts []VolumeMount `json:"volumeMounts,omitempty"`
	// Environment variables
	// +optional
	Env []corev1.EnvVar `json:"env,omitempty"`
	// Ray start parameters for workers
	// +optional
	RayStartParams map[string]string `json:"rayStartParams,omitempty"`
	// Node selector
	// +optional
	NodeSelector map[string]string `json:"nodeSelector,omitempty"`
	// Tolerations
	// +optional
	Tolerations []corev1.Toleration `json:"tolerations,omitempty"`
	// Annotations for worker pods
	// +optional
	Annotations map[string]string `json:"annotations,omitempty"`
}

// AutoTerminationSpec defines auto-termination policies
type AutoTerminationSpec struct {
	// Enabled indicates if auto-termination is enabled
	Enabled bool `json:"enabled"`
	// IdleTimeoutMinutes is the idle timeout before termination
	// +kubebuilder:validation:Minimum=1
	IdleTimeoutMinutes int32 `json:"idleTimeoutMinutes,omitempty"`
	// MaxRuntimeMinutes is the maximum runtime before termination
	// +optional
	MaxRuntimeMinutes int32 `json:"maxRuntimeMinutes,omitempty"`
}

// AdvanceConfigSpec defines advanced configuration options
type AdvanceConfigSpec struct {
	// Init script to run on cluster start
	// +optional
	InitScript string `json:"initScript,omitempty"`
	// Enable in-tree autoscaling
	// +optional
	EnableInTreeAutoscaling bool `json:"enableInTreeAutoscaling,omitempty"`
	// Autoscaler options
	// +optional
	AutoscalerOptions map[string]string `json:"autoscalerOptions,omitempty"`
	// Custom image for the cluster
	// +optional
	Image string `json:"image,omitempty"`
	// Image pull policy
	// +optional
	// +kubebuilder:validation:Enum=Always;IfNotPresent;Never
	ImagePullPolicy string `json:"imagePullPolicy,omitempty"`
	// Image pull secrets
	// +optional
	ImagePullSecrets []corev1.LocalObjectReference `json:"imagePullSecrets,omitempty"`
}

// DarwinRayClusterSpec defines the desired state of DarwinRayCluster
type DarwinRayClusterSpec struct {
	// Name is the display name of the cluster
	// +kubebuilder:validation:MinLength=1
	// +kubebuilder:validation:MaxLength=63
	Name string `json:"name"`

	// User is the owner of the cluster
	// +kubebuilder:validation:MinLength=1
	User string `json:"user"`

	// Runtime specifies the Ray runtime version
	Runtime string `json:"runtime"`

	// CloudEnv identifies which cloud environment/cluster this belongs to
	// +optional
	CloudEnv string `json:"cloudEnv,omitempty"`

	// Labels are user-defined key-value pairs for the cluster
	// +optional
	Labels map[string]string `json:"labels,omitempty"`

	// Tags are user-defined tags for categorization
	// +optional
	Tags []string `json:"tags,omitempty"`

	// HeadNode configuration
	HeadNode HeadNodeSpec `json:"headNode"`

	// WorkerGroups defines the worker group configurations
	// +optional
	WorkerGroups []WorkerGroupSpec `json:"workerGroups,omitempty"`

	// AutoTermination configuration
	// +optional
	AutoTermination *AutoTerminationSpec `json:"autoTermination,omitempty"`

	// AdvanceConfig for advanced settings
	// +optional
	AdvanceConfig *AdvanceConfigSpec `json:"advanceConfig,omitempty"`

	// Suspend indicates if the cluster should be suspended (stopped)
	// +optional
	Suspend bool `json:"suspend,omitempty"`

	// IsJobCluster indicates if this is a job cluster (ephemeral)
	// +optional
	IsJobCluster bool `json:"isJobCluster,omitempty"`
}

// DarwinRayClusterStatus defines the observed state of DarwinRayCluster
type DarwinRayClusterStatus struct {
	// Phase is the current phase of the cluster
	// +optional
	Phase ClusterPhase `json:"phase,omitempty"`

	// ActivePods is the number of currently running pods
	// +optional
	ActivePods int32 `json:"activePods,omitempty"`

	// AvailableMemoryGB is the total available memory across all pods
	// +optional
	AvailableMemoryGB int64 `json:"availableMemoryGB,omitempty"`

	// TotalCPU is the total CPU cores across all pods
	// +optional
	TotalCPU resource.Quantity `json:"totalCPU,omitempty"`

	// HeadPodIP is the IP address of the head pod
	// +optional
	HeadPodIP string `json:"headPodIP,omitempty"`

	// HeadServiceName is the name of the head service
	// +optional
	HeadServiceName string `json:"headServiceName,omitempty"`

	// JupyterURL is the URL to access Jupyter notebook
	// +optional
	JupyterURL string `json:"jupyterURL,omitempty"`

	// RayDashboardURL is the URL to access Ray dashboard
	// +optional
	RayDashboardURL string `json:"rayDashboardURL,omitempty"`

	// RayClusterRef is the name of the underlying RayCluster CR
	// +optional
	RayClusterRef string `json:"rayClusterRef,omitempty"`

	// LastTransitionTime is the last time the phase transitioned
	// +optional
	LastTransitionTime metav1.Time `json:"lastTransitionTime,omitempty"`

	// StartedAt is when the cluster was started
	// +optional
	StartedAt *metav1.Time `json:"startedAt,omitempty"`

	// ReadyWorkers is the number of ready workers
	// +optional
	ReadyWorkers int32 `json:"readyWorkers,omitempty"`

	// DesiredWorkers is the total desired workers across all groups
	// +optional
	DesiredWorkers int32 `json:"desiredWorkers,omitempty"`

	// ObservedGeneration is the generation observed by the controller
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`

	// Conditions represent the latest available observations of the cluster state
	// +optional
	// +patchMergeKey=type
	// +patchStrategy=merge
	// +listType=map
	// +listMapKey=type
	Conditions []metav1.Condition `json:"conditions,omitempty" patchStrategy:"merge" patchMergeKey:"type"`

	// Message provides additional information about the current state
	// +optional
	Message string `json:"message,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=drc
// +kubebuilder:printcolumn:name="Phase",type="string",JSONPath=".status.phase",description="Current phase"
// +kubebuilder:printcolumn:name="User",type="string",JSONPath=".spec.user",description="Cluster owner"
// +kubebuilder:printcolumn:name="Runtime",type="string",JSONPath=".spec.runtime",description="Ray runtime"
// +kubebuilder:printcolumn:name="Pods",type="integer",JSONPath=".status.activePods",description="Active pods"
// +kubebuilder:printcolumn:name="Age",type="date",JSONPath=".metadata.creationTimestamp"

// DarwinRayCluster is the Schema for the darwinrayclusters API
type DarwinRayCluster struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   DarwinRayClusterSpec   `json:"spec,omitempty"`
	Status DarwinRayClusterStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// DarwinRayClusterList contains a list of DarwinRayCluster
type DarwinRayClusterList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []DarwinRayCluster `json:"items"`
}

func init() {
	SchemeBuilder.Register(&DarwinRayCluster{}, &DarwinRayClusterList{})
}

// Condition types for DarwinRayCluster
const (
	// ConditionTypeReady indicates if the cluster is ready
	ConditionTypeReady = "Ready"
	// ConditionTypeHeadNodeReady indicates if the head node is ready
	ConditionTypeHeadNodeReady = "HeadNodeReady"
	// ConditionTypeWorkersReady indicates if all workers are ready
	ConditionTypeWorkersReady = "WorkersReady"
	// ConditionTypeJupyterReady indicates if Jupyter is ready
	ConditionTypeJupyterReady = "JupyterReady"
	// ConditionTypeRayClusterCreated indicates if the RayCluster CR was created
	ConditionTypeRayClusterCreated = "RayClusterCreated"
)

// Condition reasons
const (
	ReasonCreating           = "Creating"
	ReasonReady              = "Ready"
	ReasonNotReady           = "NotReady"
	ReasonFailed             = "Failed"
	ReasonSuspended          = "Suspended"
	ReasonTerminating        = "Terminating"
	ReasonRayClusterCreated  = "RayClusterCreated"
	ReasonRayClusterNotFound = "RayClusterNotFound"
	ReasonPodsFailed         = "PodsFailed"
	ReasonAutoTerminated     = "AutoTerminated"
)
