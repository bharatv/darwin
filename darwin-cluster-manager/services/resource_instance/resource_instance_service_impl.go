package resource_instance

import (
	"compute/cluster_manager/constants"
	dto "compute/cluster_manager/dto/resource_instance"
	"compute/cluster_manager/utils/helm_utils"
	"compute/cluster_manager/utils/kube_utils"
	"compute/cluster_manager/utils/kubeconfig_utils"
	"compute/cluster_manager/utils/logger"
	"compute/cluster_manager/utils/rest_errors"
	"compute/cluster_manager/utils/s3_utils"
	"context"
	"fmt"
	"path/filepath"

	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

const (
	ChartPath         = "./charts/"
	LocalValuesPath   = "./tmp/values/"
	LocalArtifactPath = "./tmp/artifacts/"
	LabelSelectorKey  = "darwin.dream11.com/resource-instance-id"
)

type ResourceInstanceService struct{}

// Dependency injection points for tests.
var (
	getKubeConfigPath    = kubeconfig_utils.GetKubeConfigPath
	buildConfigFromFlags = clientcmd.BuildConfigFromFlags
	newKubeClient        = func(cfg *rest.Config) (kubernetes.Interface, error) { return kubernetes.NewForConfig(cfg) }
)

func (c *ResourceInstanceService) CreateResourceArtifact(requestId string, resource dto.CreateResourceArtifact) (*dto.ResourceInstanceResponse, rest_errors.RestErr) {
	chartPath := filepath.Join(ChartPath, resource.DarwinResource)
	localValuesPath := filepath.Join(LocalValuesPath, resource.DarwinResource)
	localArtifactPath := filepath.Join(LocalArtifactPath, resource.DarwinResource, resource.ArtifactId)
	s3ArtifactPath := filepath.Join(constants.ArtifactStoreS3Prefix, resource.DarwinResource, resource.ArtifactId+".tgz")

	// Pack helm
	filePath, helmError := makeChartValues(requestId, resource.Values, chartPath, localValuesPath, resource.ArtifactId)
	if helmError != nil {
		return nil, helmError
	}

	packedChartPath, err := helm_utils.PackHelmV2(requestId, chartPath, filePath, localArtifactPath)
	if err != nil {
		logger.ErrorR(requestId, "Failed to pack helm", zap.Any("Error", err))
		return nil, err
	}
	logger.DebugR(requestId, "Packed helm chart", zap.Any("packedChartPath", packedChartPath))

	// Configure s3
	if s3Err := s3_utils.ArtifactsStore.Configure(); s3Err != nil {
		logger.ErrorR(requestId, "Failed to configure s3", zap.Any("Error", s3Err))
		return nil, s3Err
	}

	// Upload file to s3
	_, err = s3_utils.ArtifactsStore.UploadFile(packedChartPath, s3ArtifactPath)
	if err != nil {
		logger.ErrorR(requestId, "Failed to upload file to s3", zap.Any("Error", err))
		return nil, err
	}
	logger.DebugR(requestId, "Uploaded file to s3", zap.Any("s3ArtifactPath", s3ArtifactPath))

	// Delete local artifact file
	deleteFile(requestId, localValuesPath)
	deleteFile(requestId, localArtifactPath)

	return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Artifact Creation Success", Data: gin.H{"artifact_id": resource.ArtifactId}}, nil
}

func (c *ResourceInstanceService) UpdateResourceArtifactChart(requestId string, resource dto.UpdateResourceArtifactChart) (*dto.ResourceInstanceResponse, rest_errors.RestErr) {
	// Configure s3
	if s3Err := s3_utils.ArtifactsStore.Configure(); s3Err != nil {
		logger.ErrorR(requestId, "Failed to configure s3", zap.Any("Error", s3Err))
		return nil, s3Err
	}

	chartPath := filepath.Join(ChartPath, resource.DarwinResource)
	localValuesPath := filepath.Join(LocalValuesPath, resource.DarwinResource)
	localArtifactPath := filepath.Join(LocalArtifactPath, resource.DarwinResource, resource.ArtifactId)
	s3ArtifactPath := filepath.Join(constants.ArtifactStoreS3Prefix, resource.DarwinResource, resource.ArtifactId+".tgz")

	// Download artifact from s3
	if s3Err := s3_utils.ArtifactsStore.DownloadFile(localArtifactPath+".tgz", s3ArtifactPath); s3Err != nil {
		logger.ErrorR(requestId, "Failed to download file from s3", zap.Any("Error", s3Err))
		return nil, s3Err
	}
	logger.DebugR(requestId, "Downloaded file from s3", zap.Any("localArtifactPath", localArtifactPath+".tgz"))

	// Unpack Helm
	chart, err := helm_utils.UnpackHelm(requestId, localArtifactPath+".tgz")
	if err != nil {
		return nil, err
	}

	// Pack helm with older values file
	filePath, helmError := makeChartValues(requestId, chart.Values, chartPath, localValuesPath, resource.ArtifactId)
	if helmError != nil {
		return nil, helmError
	}

	path, err := helm_utils.PackHelmV2(requestId, chartPath, filePath, localArtifactPath)
	if err != nil {
		logger.ErrorR(requestId, "Failed to pack helm", zap.Any("Error", err))
		return nil, err
	}
	logger.DebugR(requestId, "Packed helm chart", zap.Any("path", path))

	// Upload file to s3
	_, err = s3_utils.ArtifactsStore.UploadFile(path, s3ArtifactPath)
	if err != nil {
		logger.ErrorR(requestId, "Failed to upload file to s3", zap.Any("Error", err))
		return nil, err
	}
	logger.DebugR(requestId, "Uploaded file to s3", zap.Any("s3ArtifactPath", s3ArtifactPath))

	// Delete local artifact file
	deleteFile(requestId, localValuesPath)
	deleteFile(requestId, localArtifactPath)
	deleteFile(requestId, localArtifactPath+".tgz")

	return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Chart Updation Success", Data: gin.H{"artifact_id": resource.ArtifactId}}, nil
}

func (c *ResourceInstanceService) UpdateResourceArtifactValues(requestId string, resource dto.UpdateResourceArtifactValues) (*dto.ResourceInstanceResponse, rest_errors.RestErr) {
	// Configure s3
	if s3Err := s3_utils.ArtifactsStore.Configure(); s3Err != nil {
		logger.ErrorR(requestId, "Failed to configure s3", zap.Any("Error", s3Err))
		return nil, s3Err
	}

	chartPath := filepath.Join(ChartPath, resource.DarwinResource)
	localValuesPath := filepath.Join(LocalValuesPath, resource.DarwinResource)
	localArtifactPath := filepath.Join(LocalArtifactPath, resource.DarwinResource, resource.ArtifactId)
	s3ArtifactPath := filepath.Join(constants.ArtifactStoreS3Prefix, resource.DarwinResource, resource.ArtifactId+".tgz")

	// Download artifact from s3
	if s3Err := s3_utils.ArtifactsStore.DownloadFile(localArtifactPath+".tgz", s3ArtifactPath); s3Err != nil {
		logger.ErrorR(requestId, "Failed to download file from s3", zap.Any("Error", s3Err))
		return nil, s3Err
	}
	logger.DebugR(requestId, "Downloaded file from s3", zap.Any("localArtifactPath", localArtifactPath+".tgz"))

	// Unpack Helm
	chart, err := helm_utils.UnpackHelm(requestId, localArtifactPath+".tgz")
	if err != nil {
		return nil, err
	}

	// Pack helm with new values
	filePath, err := makeYaml(requestId, resource.Values, chart, localValuesPath, resource.ArtifactId)
	if err != nil {
		return nil, err
	}

	path, err := helm_utils.PackHelmV2(requestId, chartPath, filePath, localArtifactPath)
	if err != nil {
		logger.ErrorR(requestId, "Failed to pack helm", zap.Any("Error", err))
		return nil, err
	}
	logger.DebugR(requestId, "Packed helm chart with new values", zap.Any("path", path))

	// Upload file to s3
	_, err = s3_utils.ArtifactsStore.UploadFile(path, s3ArtifactPath)
	if err != nil {
		logger.ErrorR(requestId, "Failed to upload file to s3", zap.Any("Error", err))
		return nil, err
	}
	logger.DebugR(requestId, "Uploaded file to s3", zap.Any("s3ArtifactPath", s3ArtifactPath))

	// Delete local artifact file
	deleteFile(requestId, localValuesPath)
	deleteFile(requestId, localArtifactPath)
	deleteFile(requestId, localArtifactPath+".tgz")

	return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Values Updation Success", Data: gin.H{"artifact_id": resource.ArtifactId}}, nil
}

func (c *ResourceInstanceService) StartResourceInstance(requestId string, resource dto.StartResourceInstance) (*dto.ResourceInstanceResponse, rest_errors.RestErr) {
	// Configure s3
	if s3Err := s3_utils.ArtifactsStore.Configure(); s3Err != nil {
		logger.ErrorR(requestId, "Failed to configure s3", zap.Any("Error", s3Err))
		return nil, s3Err
	}

	localArtifactPath := filepath.Join(LocalArtifactPath, resource.DarwinResource, resource.ArtifactId+".tgz")
	s3ArtifactPath := filepath.Join(constants.ArtifactStoreS3Prefix, resource.DarwinResource, resource.ArtifactId+".tgz")
	kubeConfigPath, kubeConfigErr := kubeconfig_utils.GetKubeConfigPath(resource.KubeCluster)
	if kubeConfigErr != nil {
		logger.ErrorR(requestId, "Failed to get kubeconfig path", zap.Any("Error", kubeConfigErr))
		return nil, kubeConfigErr
	}

	// Download artifact from s3
	if s3Err := s3_utils.ArtifactsStore.DownloadFile(localArtifactPath, s3ArtifactPath); s3Err != nil {
		logger.ErrorR(requestId, "Failed to download file from s3", zap.Any("Error", s3Err))
		return nil, s3Err
	}
	logger.DebugR(requestId, "Downloaded file from s3", zap.Any("localArtifactPath", localArtifactPath))

	// Install helm chart
	_, err := helm_utils.InstallorUpgradeHelmChartWithRetries(kubeConfigPath, localArtifactPath, resource.ResourceId, resource.KubeNamespace)
	if err != nil {
		logger.ErrorR(requestId, "Failed to install helm chart", zap.Any("Error", err))
		return nil, rest_errors.NewInternalServerError("Failed to install helm chart", err)
	}
	logger.DebugR(requestId, "Installed helm chart", zap.Any("resourceId", resource.ResourceId))

	// Delete local artifact file
	deleteFile(requestId, localArtifactPath)

	return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Resource Instance Start Accepted", Data: gin.H{"resource_id": resource.ResourceId}}, nil
}

func (c *ResourceInstanceService) StopResourceInstance(requestId string, resource dto.StopResourceInstance) (*dto.ResourceInstanceResponse, rest_errors.RestErr) {
	kubeConfigPath, kubeConfigErr := kubeconfig_utils.GetKubeConfigPath(resource.KubeCluster)
	if kubeConfigErr != nil {
		logger.ErrorR(requestId, "Failed to get kubeconfig path", zap.Any("Error", kubeConfigErr))
		return nil, kubeConfigErr
	}

	// Delete helm release
	_, err := helm_utils.DeleteHelmRelease(kubeConfigPath, resource.ResourceId, resource.KubeNamespace)
	if err != nil {
		logger.ErrorR(requestId, "Failed to delete helm release", zap.Any("Error", err))
		return nil, err
	}
	logger.DebugR(requestId, "Deleted helm release", zap.Any("resourceId", resource.ResourceId))

	return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Resource Instance Stop Accepted", Data: gin.H{"resource_id": resource.ResourceId}}, nil
}

func (c *ResourceInstanceService) ResourceInstanceStatus(requestId string, resource dto.ResourceInstanceStatus) (*dto.ResourceInstanceResponse, rest_errors.RestErr) {
	kubeConfigPath, kubeConfigErr := kubeconfig_utils.GetKubeConfigPath(resource.KubeCluster)
	if kubeConfigErr != nil {
		logger.ErrorR(requestId, "Failed to get kubeconfig path", zap.Any("Error", kubeConfigErr))
		return nil, kubeConfigErr
	}

	labelSelector := fmt.Sprintf("%s=%s", LabelSelectorKey, resource.ResourceId)

	var resourceInstanceStatus dto.ResourceStatus

	pods, err := kube_utils.GetPodsStatus(requestId, kubeConfigPath, resource.KubeNamespace, labelSelector)
	if err != nil {
		return nil, err
	}
	resourceInstanceStatus.Pods = pods

	data := gin.H{"resource_id": resource.ResourceId, "status": resourceInstanceStatus}
	return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Resource Instance Status Retrieved Successfully", Data: data}, nil
}

func (c *ResourceInstanceService) UpdateServiceSelector(requestId string, resource dto.UpdateServiceSelector) (*dto.ResourceInstanceResponse, rest_errors.RestErr) {
	kubeConfigPath, kubeConfigErr := getKubeConfigPath(resource.KubeCluster)
	if kubeConfigErr != nil {
		logger.ErrorR(requestId, "Failed to get kubeconfig path", zap.Any("Error", kubeConfigErr))
		return nil, kubeConfigErr
	}

	config, err := buildConfigFromFlags("", kubeConfigPath)
	if err != nil {
		return nil, rest_errors.NewInternalServerError("Failed to build config from kubeconfig path", err)
	}

	clientSet, err := newKubeClient(config)
	if err != nil {
		return nil, rest_errors.NewInternalServerError("Failed to initiate k8s client", err)
	}

	// For darwin-fastapi-serve, Service name is the Helm release name (resource_id)
	serviceName := resource.ResourceId

	svc, err := clientSet.CoreV1().Services(resource.KubeNamespace).Get(context.TODO(), serviceName, metav1.GetOptions{})
	if err != nil {
		return nil, rest_errors.NewInternalServerError("Failed to get Service", err)
	}

	before := map[string]string{}
	for k, v := range svc.Spec.Selector {
		before[k] = v
	}

	// Idempotency
	if len(before) == len(resource.ServiceSelector) {
		match := true
		for k, v := range resource.ServiceSelector {
			if before[k] != v {
				match = false
				break
			}
		}
		if match {
			data := gin.H{
				"resource_id":     resource.ResourceId,
				"service_name":    serviceName,
				"before_selector": before,
				"after_selector":  before,
				"idempotent":      true,
			}
			return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Service selector already up to date", Data: data}, nil
		}
	}

	svc.Spec.Selector = resource.ServiceSelector
	updated, err := clientSet.CoreV1().Services(resource.KubeNamespace).Update(context.TODO(), svc, metav1.UpdateOptions{})
	if err != nil {
		return nil, rest_errors.NewInternalServerError("Failed to update Service selector", err)
	}

	after := map[string]string{}
	for k, v := range updated.Spec.Selector {
		after[k] = v
	}

	data := gin.H{
		"resource_id":     resource.ResourceId,
		"service_name":    serviceName,
		"before_selector": before,
		"after_selector":  after,
		"idempotent":      false,
	}
	return &dto.ResourceInstanceResponse{Status: "SUCCESS", Message: "Service selector updated", Data: data}, nil
}
