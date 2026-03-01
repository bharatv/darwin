package resource_instance

// CreateResourceArtifact to Create an artifact of Resource Instance
type CreateResourceArtifact struct {
	ArtifactId     string                 `json:"artifact_id"`
	DarwinResource string                 `json:"darwin_resource"`
	Version        string                 `json:"version,omitempty"`
	Values         map[string]interface{} `json:"values"`
}

// UpdateResourceArtifactChart to Update chart of an artifact of Resource Instance
type UpdateResourceArtifactChart struct {
	ArtifactId     string `json:"artifact_id"`
	DarwinResource string `json:"darwin_resource"`
	Version        string `json:"version,omitempty"`
}

// UpdateResourceArtifactValues to Update values of an artifact of Resource Instance
type UpdateResourceArtifactValues struct {
	ArtifactId     string                 `json:"artifact_id"`
	Values         map[string]interface{} `json:"values"`
	DarwinResource string                 `json:"darwin_resource"`
}

// StartResourceInstance to Start an Instance
type StartResourceInstance struct {
	ResourceId     string `json:"resource_id"`
	ArtifactId     string `json:"artifact_id"`
	KubeCluster    string `json:"kube_cluster"`
	KubeNamespace  string `json:"kube_namespace"`
	DarwinResource string `json:"darwin_resource"`
}

// StopResourceInstance to Stop an Instance
type StopResourceInstance struct {
	ResourceId    string `json:"resource_id"`
	KubeCluster   string `json:"kube_cluster"`
	KubeNamespace string `json:"kube_namespace"`
}

// ResourceInstanceStatus to Get status of an Instance
type ResourceInstanceStatus struct {
	ResourceId    string `json:"resource_id"`
	KubeCluster   string `json:"kube_cluster"`
	KubeNamespace string `json:"kube_namespace"`
}

// UpdateServiceSelector to patch Service.spec.selector of an Instance's Service
type UpdateServiceSelector struct {
	ResourceId       string            `json:"resource_id"`
	KubeCluster      string            `json:"kube_cluster"`
	KubeNamespace    string            `json:"kube_namespace"`
	ServiceSelector  map[string]string `json:"service_selector"`
}
