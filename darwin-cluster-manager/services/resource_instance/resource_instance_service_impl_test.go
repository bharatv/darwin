package resource_instance

import (
	dto "compute/cluster_manager/dto/resource_instance"
	"compute/cluster_manager/utils/rest_errors"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/kubernetes/fake"
	"k8s.io/client-go/rest"
)

func TestUpdateServiceSelector_UpdatesSelector(t *testing.T) {
	origGet := getKubeConfigPath
	origBuild := buildConfigFromFlags
	origNew := newKubeClient
	defer func() {
		getKubeConfigPath = origGet
		buildConfigFromFlags = origBuild
		newKubeClient = origNew
	}()

	getKubeConfigPath = func(cluster string) (string, rest_errors.RestErr) {
		return "/tmp/kubeconfig", nil
	}
	buildConfigFromFlags = func(masterUrl, kubeconfigPath string) (*rest.Config, error) {
		return &rest.Config{}, nil
	}

	ns := "serve"
	svcName := "my-svc"
	client := fake.NewSimpleClientset(&corev1.Service{
		ObjectMeta: metav1.ObjectMeta{Name: svcName, Namespace: ns},
		Spec:       corev1.ServiceSpec{Selector: map[string]string{"a": "b"}},
	})
	newKubeClient = func(cfg *rest.Config) (kubernetes.Interface, error) { return client, nil }

	svc := &ResourceInstanceService{}
	resp, err := svc.UpdateServiceSelector("rid", dto.UpdateServiceSelector{
		ResourceId:      svcName,
		KubeCluster:     "kind",
		KubeNamespace:   ns,
		ServiceSelector: map[string]string{"k": "v"},
	})
	if err != nil {
		t.Fatalf("expected nil err, got %v", err)
	}
	if resp == nil || resp.Status != "SUCCESS" {
		t.Fatalf("expected SUCCESS response, got %#v", resp)
	}
}

func TestUpdateServiceSelector_Idempotent(t *testing.T) {
	origGet := getKubeConfigPath
	origBuild := buildConfigFromFlags
	origNew := newKubeClient
	defer func() {
		getKubeConfigPath = origGet
		buildConfigFromFlags = origBuild
		newKubeClient = origNew
	}()

	getKubeConfigPath = func(cluster string) (string, rest_errors.RestErr) {
		return "/tmp/kubeconfig", nil
	}
	buildConfigFromFlags = func(masterUrl, kubeconfigPath string) (*rest.Config, error) {
		return &rest.Config{}, nil
	}

	ns := "serve"
	svcName := "my-svc"
	client := fake.NewSimpleClientset(&corev1.Service{
		ObjectMeta: metav1.ObjectMeta{Name: svcName, Namespace: ns},
		Spec:       corev1.ServiceSpec{Selector: map[string]string{"k": "v"}},
	})
	newKubeClient = func(cfg *rest.Config) (kubernetes.Interface, error) { return client, nil }

	svc := &ResourceInstanceService{}
	resp, err := svc.UpdateServiceSelector("rid", dto.UpdateServiceSelector{
		ResourceId:      svcName,
		KubeCluster:     "kind",
		KubeNamespace:   ns,
		ServiceSelector: map[string]string{"k": "v"},
	})
	if err != nil {
		t.Fatalf("expected nil err, got %v", err)
	}
	if resp == nil || resp.Status != "SUCCESS" {
		t.Fatalf("expected SUCCESS response, got %#v", resp)
	}
}
