package resource_instance

import (
	dto "compute/cluster_manager/dto/resource_instance"
	"compute/cluster_manager/utils/rest_errors"
)

type ResourceInstanceInterface interface {
	CreateResourceArtifact(requestId string, resource dto.CreateResourceArtifact) (*dto.ResourceInstanceResponse, rest_errors.RestErr)
	UpdateResourceArtifactChart(requestId string, resource dto.UpdateResourceArtifactChart) (*dto.ResourceInstanceResponse, rest_errors.RestErr)
	UpdateResourceArtifactValues(requestId string, resource dto.UpdateResourceArtifactValues) (*dto.ResourceInstanceResponse, rest_errors.RestErr)
	StartResourceInstance(requestId string, resource dto.StartResourceInstance) (*dto.ResourceInstanceResponse, rest_errors.RestErr)
	StopResourceInstance(requestId string, resource dto.StopResourceInstance) (*dto.ResourceInstanceResponse, rest_errors.RestErr)
	ResourceInstanceStatus(requestId string, resource dto.ResourceInstanceStatus) (*dto.ResourceInstanceResponse, rest_errors.RestErr)
	UpdateServiceSelector(requestId string, resource dto.UpdateServiceSelector) (*dto.ResourceInstanceResponse, rest_errors.RestErr)
}
