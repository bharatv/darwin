package resource_instance

import (
	dto "compute/cluster_manager/dto/resource_instance"
	service "compute/cluster_manager/services/resource_instance"
	"compute/cluster_manager/utils/rest_errors"
)

func ValidateCreateResourceArtifactRequest(body dto.CreateResourceArtifact) (service.ResourceInstanceInterface, rest_errors.RestErr) {
	if body.DarwinResource == "" {
		return nil, rest_errors.NewBadRequestError("darwin_resource is mandatory", nil)
	}
	//if body.Version == "" {
	//	return nil, rest_errors.NewBadRequestError("version is mandatory", nil)
	//}
	if body.ArtifactId == "" {
		return nil, rest_errors.NewBadRequestError("artifact_id for resource is mandatory", nil)
	}

	return &service.ResourceInstanceService{}, nil
}

func ValidateUpdateResourceArtifactChartRequest(body dto.UpdateResourceArtifactChart) (service.ResourceInstanceInterface, rest_errors.RestErr) {
	if body.DarwinResource == "" {
		return nil, rest_errors.NewBadRequestError("darwin_resource is mandatory", nil)
	}
	//if body.Version == "" {
	//	return nil, rest_errors.NewBadRequestError("version is mandatory", nil)
	//}
	if body.ArtifactId == "" {
		return nil, rest_errors.NewBadRequestError("artifact_id for resource is mandatory", nil)
	}

	return &service.ResourceInstanceService{}, nil
}

func ValidateUpdateResourceArtifactValuesRequest(body dto.UpdateResourceArtifactValues) (service.ResourceInstanceInterface, rest_errors.RestErr) {
	if body.DarwinResource == "" {
		return nil, rest_errors.NewBadRequestError("darwin_resource is mandatory", nil)
	}
	//if body.Version == "" {
	//	return nil, rest_errors.NewBadRequestError("version is mandatory", nil)
	//}
	if body.ArtifactId == "" {
		return nil, rest_errors.NewBadRequestError("artifact_id for resource is mandatory", nil)
	}

	return &service.ResourceInstanceService{}, nil
}

func ValidateStartResourceInstanceRequest(body dto.StartResourceInstance) (service.ResourceInstanceInterface, rest_errors.RestErr) {
	if body.ResourceId == "" {
		return nil, rest_errors.NewBadRequestError("resource_id is mandatory", nil)
	}
	if body.ArtifactId == "" {
		return nil, rest_errors.NewBadRequestError("artifact_id is mandatory", nil)
	}
	if body.KubeCluster == "" {
		return nil, rest_errors.NewBadRequestError("kube_cluster is mandatory", nil)
	}
	if body.KubeNamespace == "" {
		return nil, rest_errors.NewBadRequestError("kube_namespace is mandatory", nil)
	}
	if body.DarwinResource == "" {
		return nil, rest_errors.NewBadRequestError("darwin_resource is mandatory", nil)
	}

	return &service.ResourceInstanceService{}, nil
}

func ValidateStopResourceInstanceRequest(body dto.StopResourceInstance) (service.ResourceInstanceInterface, rest_errors.RestErr) {
	if body.ResourceId == "" {
		return nil, rest_errors.NewBadRequestError("resource_id is mandatory", nil)
	}
	if body.KubeCluster == "" {
		return nil, rest_errors.NewBadRequestError("kube_cluster is mandatory", nil)
	}
	if body.KubeNamespace == "" {
		return nil, rest_errors.NewBadRequestError("kube_namespace is mandatory", nil)
	}

	return &service.ResourceInstanceService{}, nil
}

func ValidateResourceInstanceStatusRequest(body dto.ResourceInstanceStatus) (service.ResourceInstanceInterface, rest_errors.RestErr) {
	if body.ResourceId == "" {
		return nil, rest_errors.NewBadRequestError("resource_id is mandatory", nil)
	}
	if body.KubeCluster == "" {
		return nil, rest_errors.NewBadRequestError("kube_cluster is mandatory", nil)
	}
	if body.KubeNamespace == "" {
		return nil, rest_errors.NewBadRequestError("kube_namespace is mandatory", nil)
	}

	return &service.ResourceInstanceService{}, nil
}

func ValidateUpdateServiceSelectorRequest(body dto.UpdateServiceSelector) (service.ResourceInstanceInterface, rest_errors.RestErr) {
	if body.ResourceId == "" {
		return nil, rest_errors.NewBadRequestError("resource_id is mandatory", nil)
	}
	if body.KubeCluster == "" {
		return nil, rest_errors.NewBadRequestError("kube_cluster is mandatory", nil)
	}
	if body.KubeNamespace == "" {
		return nil, rest_errors.NewBadRequestError("kube_namespace is mandatory", nil)
	}
	if body.ServiceSelector == nil || len(body.ServiceSelector) == 0 {
		return nil, rest_errors.NewBadRequestError("service_selector is mandatory and must be non-empty", nil)
	}

	return &service.ResourceInstanceService{}, nil
}
