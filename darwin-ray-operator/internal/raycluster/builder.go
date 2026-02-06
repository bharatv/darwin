package raycluster

import (
	"fmt"

	rayv1 "github.com/ray-project/kuberay/ray-operator/apis/ray/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	computev1alpha1 "github.com/darwin/darwin-ray-operator/api/v1alpha1"
)

const (
	// DefaultRayVersion is the default Ray version
	DefaultRayVersion = "2.37.0"
	// DefaultImageRepository is the default image repository
	DefaultImageRepository = "rayproject/ray"
)

// BuildRayCluster builds a RayCluster CR from DarwinRayCluster spec
func BuildRayCluster(drc *computev1alpha1.DarwinRayCluster, name, namespace string) (*rayv1.RayCluster, error) {
	rayCluster := &rayv1.RayCluster{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			Labels:    buildLabels(drc),
			Annotations: map[string]string{
				"compute.darwin.io/darwin-cluster-id": drc.Name,
				"compute.darwin.io/user":              drc.Spec.User,
				"compute.darwin.io/runtime":           drc.Spec.Runtime,
			},
		},
		Spec: rayv1.RayClusterSpec{
			RayVersion:              getRayVersion(drc),
			EnableInTreeAutoscaling: getEnableAutoscaling(drc),
			HeadGroupSpec:           buildHeadGroupSpec(drc),
			WorkerGroupSpecs:        buildWorkerGroupSpecs(drc),
		},
	}

	// Add autoscaler options if enabled
	if drc.Spec.AdvanceConfig != nil && drc.Spec.AdvanceConfig.EnableInTreeAutoscaling {
		rayCluster.Spec.AutoscalerOptions = buildAutoscalerOptions(drc)
	}

	return rayCluster, nil
}

// buildLabels builds labels for the RayCluster
func buildLabels(drc *computev1alpha1.DarwinRayCluster) map[string]string {
	labels := map[string]string{
		"app.kubernetes.io/name":       "ray-cluster",
		"app.kubernetes.io/instance":   drc.Name,
		"app.kubernetes.io/managed-by": "darwin-ray-operator",
		"rayCluster":                   fmt.Sprintf("%s-kuberay", drc.Name),
		"compute.darwin.io/cluster-id": drc.Name,
		"compute.darwin.io/user":       drc.Spec.User,
	}

	// Add user-defined labels
	for k, v := range drc.Spec.Labels {
		labels[fmt.Sprintf("darwin.io/%s", k)] = v
	}

	return labels
}

// getRayVersion extracts Ray version from runtime or uses default
func getRayVersion(drc *computev1alpha1.DarwinRayCluster) string {
	// Runtime format is typically "X.Y" where we map it to Ray version
	// In production, this would look up the actual Ray version from a runtime registry
	if drc.Spec.Runtime != "" {
		return DefaultRayVersion
	}
	return DefaultRayVersion
}

// getEnableAutoscaling checks if autoscaling should be enabled
func getEnableAutoscaling(drc *computev1alpha1.DarwinRayCluster) *bool {
	if drc.Spec.AdvanceConfig != nil {
		return &drc.Spec.AdvanceConfig.EnableInTreeAutoscaling
	}
	enabled := false
	return &enabled
}

// buildHeadGroupSpec builds the head group specification
func buildHeadGroupSpec(drc *computev1alpha1.DarwinRayCluster) rayv1.HeadGroupSpec {
	headSpec := drc.Spec.HeadNode
	image := getImage(drc)

	// Build ray start params
	rayStartParams := map[string]string{
		"dashboard-host": "0.0.0.0",
	}
	for k, v := range headSpec.RayStartParams {
		rayStartParams[k] = v
	}

	// Build container
	container := corev1.Container{
		Name:  "ray-head",
		Image: image,
		Resources: corev1.ResourceRequirements{
			Requests: buildResourceRequests(headSpec.Resources),
			Limits:   buildResourceLimits(headSpec.Resources),
		},
		Env:          buildEnvVars(headSpec.Env, drc),
		VolumeMounts: buildVolumeMounts(headSpec.VolumeMounts),
		Ports:        buildHeadPorts(drc),
		LivenessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{
					Command: []string{
						"bash", "-c",
						"wget -T 2 -q -O- http://localhost:52365/api/local_raylet_healthz | grep success && wget -T 2 -q -O- http://localhost:8265/api/gcs_healthz | grep success",
					},
				},
			},
			InitialDelaySeconds: 60,
			PeriodSeconds:       15,
			FailureThreshold:    10,
			TimeoutSeconds:      3,
		},
		ReadinessProbe: &corev1.Probe{
			ProbeHandler: corev1.ProbeHandler{
				Exec: &corev1.ExecAction{
					Command: []string{
						"bash", "-c",
						"wget -T 2 -q -O- http://localhost:52365/api/local_raylet_healthz | grep success && wget -T 2 -q -O- http://localhost:8265/api/gcs_healthz | grep success",
					},
				},
			},
			InitialDelaySeconds: 60,
			PeriodSeconds:       15,
			FailureThreshold:    2,
			TimeoutSeconds:      3,
		},
	}

	// Set image pull policy
	if drc.Spec.AdvanceConfig != nil && drc.Spec.AdvanceConfig.ImagePullPolicy != "" {
		container.ImagePullPolicy = corev1.PullPolicy(drc.Spec.AdvanceConfig.ImagePullPolicy)
	}

	spec := rayv1.HeadGroupSpec{
		RayStartParams: rayStartParams,
		Template: corev1.PodTemplateSpec{
			ObjectMeta: metav1.ObjectMeta{
				Labels:      buildPodLabels(drc, "head"),
				Annotations: headSpec.Annotations,
			},
			Spec: corev1.PodSpec{
				Containers:                    []corev1.Container{container},
				Volumes:                       buildVolumes(headSpec.VolumeMounts),
				NodeSelector:                  headSpec.NodeSelector,
				Tolerations:                   headSpec.Tolerations,
				ServiceAccountName:            headSpec.ServiceAccountName,
				AutomountServiceAccountToken:  boolPtr(true),
				TerminationGracePeriodSeconds: int64Ptr(0),
			},
		},
		ServiceType: corev1.ServiceTypeClusterIP,
	}

	// Add image pull secrets
	if drc.Spec.AdvanceConfig != nil && len(drc.Spec.AdvanceConfig.ImagePullSecrets) > 0 {
		spec.Template.Spec.ImagePullSecrets = drc.Spec.AdvanceConfig.ImagePullSecrets
	}

	return spec
}

// buildWorkerGroupSpecs builds worker group specifications
func buildWorkerGroupSpecs(drc *computev1alpha1.DarwinRayCluster) []rayv1.WorkerGroupSpec {
	if len(drc.Spec.WorkerGroups) == 0 {
		return nil
	}

	image := getImage(drc)
	specs := make([]rayv1.WorkerGroupSpec, 0, len(drc.Spec.WorkerGroups))

	for _, wg := range drc.Spec.WorkerGroups {
		// Build ray start params
		rayStartParams := map[string]string{}
		for k, v := range wg.RayStartParams {
			rayStartParams[k] = v
		}

		// Build container
		container := corev1.Container{
			Name:  "ray-worker",
			Image: image,
			Resources: corev1.ResourceRequirements{
				Requests: buildResourceRequests(wg.Resources),
				Limits:   buildResourceLimits(wg.Resources),
			},
			Env:          buildEnvVars(wg.Env, drc),
			VolumeMounts: buildVolumeMounts(wg.VolumeMounts),
			Ports:        buildWorkerPorts(),
			LivenessProbe: &corev1.Probe{
				ProbeHandler: corev1.ProbeHandler{
					Exec: &corev1.ExecAction{
						Command: []string{
							"bash", "-c",
							"wget -T 2 -q -O- http://localhost:52365/api/local_raylet_healthz | grep success",
						},
					},
				},
				InitialDelaySeconds: 60,
				PeriodSeconds:       15,
				FailureThreshold:    10,
				TimeoutSeconds:      3,
			},
			ReadinessProbe: &corev1.Probe{
				ProbeHandler: corev1.ProbeHandler{
					Exec: &corev1.ExecAction{
						Command: []string{
							"bash", "-c",
							"wget -T 2 -q -O- http://localhost:52365/api/local_raylet_healthz | grep success",
						},
					},
				},
				InitialDelaySeconds: 60,
				PeriodSeconds:       15,
				FailureThreshold:    2,
				TimeoutSeconds:      3,
			},
		}

		// Set image pull policy
		if drc.Spec.AdvanceConfig != nil && drc.Spec.AdvanceConfig.ImagePullPolicy != "" {
			container.ImagePullPolicy = corev1.PullPolicy(drc.Spec.AdvanceConfig.ImagePullPolicy)
		}

		spec := rayv1.WorkerGroupSpec{
			GroupName:      wg.Name,
			Replicas:       int32Ptr(wg.Replicas),
			MinReplicas:    int32Ptr(wg.MinReplicas),
			MaxReplicas:    int32Ptr(maxInt32(wg.MaxReplicas, wg.Replicas)),
			RayStartParams: rayStartParams,
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels:      buildPodLabels(drc, "worker"),
					Annotations: wg.Annotations,
				},
				Spec: corev1.PodSpec{
					Containers:                    []corev1.Container{container},
					Volumes:                       buildVolumes(wg.VolumeMounts),
					NodeSelector:                  wg.NodeSelector,
					Tolerations:                   wg.Tolerations,
					ServiceAccountName:            wg.ServiceAccountName,
					AutomountServiceAccountToken:  boolPtr(true),
					TerminationGracePeriodSeconds: int64Ptr(0),
				},
			},
		}

		// Add image pull secrets
		if drc.Spec.AdvanceConfig != nil && len(drc.Spec.AdvanceConfig.ImagePullSecrets) > 0 {
			spec.Template.Spec.ImagePullSecrets = drc.Spec.AdvanceConfig.ImagePullSecrets
		}

		specs = append(specs, spec)
	}

	return specs
}

// buildAutoscalerOptions builds autoscaler options
func buildAutoscalerOptions(drc *computev1alpha1.DarwinRayCluster) *rayv1.AutoscalerOptions {
	if drc.Spec.AdvanceConfig == nil || drc.Spec.AdvanceConfig.AutoscalerOptions == nil {
		return nil
	}

	// Build from advance config
	options := &rayv1.AutoscalerOptions{}

	// Parse common options
	if upscalingMode, ok := drc.Spec.AdvanceConfig.AutoscalerOptions["upscalingMode"]; ok {
		mode := rayv1.UpscalingMode(upscalingMode)
		options.UpscalingMode = &mode
	}

	return options
}

// getImage returns the container image to use
func getImage(drc *computev1alpha1.DarwinRayCluster) string {
	if drc.Spec.AdvanceConfig != nil && drc.Spec.AdvanceConfig.Image != "" {
		return drc.Spec.AdvanceConfig.Image
	}
	// Default image based on runtime
	// In production, this would look up the image from a runtime registry
	return fmt.Sprintf("%s:%s", DefaultImageRepository, DefaultRayVersion)
}

// buildPodLabels builds labels for pods
func buildPodLabels(drc *computev1alpha1.DarwinRayCluster, nodeType string) map[string]string {
	labels := map[string]string{
		"ray.io/is-ray-node":           "yes",
		"ray.io/node-type":             nodeType,
		"compute.darwin.io/cluster-id": drc.Name,
		"compute.darwin.io/user":       drc.Spec.User,
		"app.kubernetes.io/name":       "ray-cluster",
		"app.kubernetes.io/instance":   drc.Name,
		"app.kubernetes.io/managed-by": "darwin-ray-operator",
	}
	return labels
}

// buildResourceRequests builds resource requests from ResourceSpec
func buildResourceRequests(res computev1alpha1.ResourceSpec) corev1.ResourceList {
	requests := corev1.ResourceList{
		corev1.ResourceCPU:    resource.MustParse(res.CPU),
		corev1.ResourceMemory: resource.MustParse(fmt.Sprintf("%dGi", res.MemoryGB)),
	}
	if res.GPU > 0 && res.GPUType != "" {
		requests[corev1.ResourceName(res.GPUType)] = resource.MustParse(fmt.Sprintf("%d", res.GPU))
	}
	return requests
}

// buildResourceLimits builds resource limits from ResourceSpec
func buildResourceLimits(res computev1alpha1.ResourceSpec) corev1.ResourceList {
	limits := corev1.ResourceList{
		corev1.ResourceCPU:    resource.MustParse(res.CPU),
		corev1.ResourceMemory: resource.MustParse(fmt.Sprintf("%dGi", res.MemoryGB)),
	}
	if res.GPU > 0 && res.GPUType != "" {
		limits[corev1.ResourceName(res.GPUType)] = resource.MustParse(fmt.Sprintf("%d", res.GPU))
	}
	return limits
}

// buildEnvVars builds environment variables
func buildEnvVars(envVars []corev1.EnvVar, drc *computev1alpha1.DarwinRayCluster) []corev1.EnvVar {
	// Add default env vars
	defaultEnvs := []corev1.EnvVar{
		{
			Name:  "DARWIN_CLUSTER_ID",
			Value: drc.Name,
		},
		{
			Name:  "DARWIN_USER",
			Value: drc.Spec.User,
		},
		{
			Name:  "DARWIN_RUNTIME",
			Value: drc.Spec.Runtime,
		},
	}

	// Merge with user-provided env vars
	result := append(defaultEnvs, envVars...)
	return result
}

// buildVolumeMounts builds volume mounts from VolumeMount specs
func buildVolumeMounts(mounts []computev1alpha1.VolumeMount) []corev1.VolumeMount {
	if len(mounts) == 0 {
		return nil
	}

	result := make([]corev1.VolumeMount, 0, len(mounts))
	for _, m := range mounts {
		result = append(result, corev1.VolumeMount{
			Name:      m.Name,
			MountPath: m.MountPath,
			ReadOnly:  m.ReadOnly,
		})
	}
	return result
}

// buildVolumes builds volumes from VolumeMount specs
func buildVolumes(mounts []computev1alpha1.VolumeMount) []corev1.Volume {
	if len(mounts) == 0 {
		return nil
	}

	result := make([]corev1.Volume, 0, len(mounts))
	for _, m := range mounts {
		vol := corev1.Volume{
			Name: m.Name,
		}

		if m.PVCName != "" {
			vol.VolumeSource = corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
					ClaimName: m.PVCName,
				},
			}
		} else if m.ConfigMapName != "" {
			vol.VolumeSource = corev1.VolumeSource{
				ConfigMap: &corev1.ConfigMapVolumeSource{
					LocalObjectReference: corev1.LocalObjectReference{
						Name: m.ConfigMapName,
					},
				},
			}
		} else if m.SecretName != "" {
			vol.VolumeSource = corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{
					SecretName: m.SecretName,
				},
			}
		} else {
			// Default to empty dir
			vol.VolumeSource = corev1.VolumeSource{
				EmptyDir: &corev1.EmptyDirVolumeSource{},
			}
		}

		result = append(result, vol)
	}
	return result
}

// buildHeadPorts builds ports for head node
func buildHeadPorts(drc *computev1alpha1.DarwinRayCluster) []corev1.ContainerPort {
	ports := []corev1.ContainerPort{
		{Name: "gcs", ContainerPort: 6379, Protocol: corev1.ProtocolTCP},
		{Name: "dashboard", ContainerPort: 8265, Protocol: corev1.ProtocolTCP},
		{Name: "client", ContainerPort: 10001, Protocol: corev1.ProtocolTCP},
		{Name: "serve", ContainerPort: 8000, Protocol: corev1.ProtocolTCP},
	}

	if drc.Spec.HeadNode.EnableJupyter {
		ports = append(ports, corev1.ContainerPort{
			Name: "jupyter", ContainerPort: 8888, Protocol: corev1.ProtocolTCP,
		})
	}

	return ports
}

// buildWorkerPorts builds ports for worker nodes
func buildWorkerPorts() []corev1.ContainerPort {
	return []corev1.ContainerPort{
		{Name: "object-manager", ContainerPort: 8076, Protocol: corev1.ProtocolTCP},
		{Name: "node-manager", ContainerPort: 8077, Protocol: corev1.ProtocolTCP},
	}
}

// Helper functions
func boolPtr(b bool) *bool {
	return &b
}

func int32Ptr(i int32) *int32 {
	return &i
}

func int64Ptr(i int64) *int64 {
	return &i
}

func maxInt32(a, b int32) int32 {
	if a > b {
		return a
	}
	return b
}
