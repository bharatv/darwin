package resource_instance

import (
	dto "compute/cluster_manager/dto/resource_instance"
	"compute/cluster_manager/utils/logger"
	"compute/cluster_manager/utils/rest_errors"
	"github.com/gin-gonic/gin"
	"go.uber.org/zap"
	"net/http"
)

func CreateResourceArtifact(c *gin.Context) {
	requestId := c.GetString("requestID")

	var body dto.CreateResourceArtifact

	// Unmarshal the request body into the body struct
	if err := c.ShouldBindJSON(&body); err != nil {
		restErr := rest_errors.NewBadRequestError("Invalid request body", err)
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to unmarshal request body", zap.Any("Error", err))
		return
	}

	logger.InfoR(requestId, "Creating resource instance artifact", zap.Any("body", body))
	service, restErr := ValidateCreateResourceArtifactRequest(body)
	if restErr != nil {
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to validate request", zap.Any("Error", restErr))
		return
	}

	response, err := service.CreateResourceArtifact(requestId, body)
	if err != nil {
		c.JSON(err.Status(), gin.H{"status": "ERROR", "message": err.Message(), "causes": err.Causes()})
		return
	}

	c.JSON(http.StatusCreated, response)
	logger.InfoR(requestId, "Resource instance artifact created successfully", zap.Any("response", response))
}

func UpdateResourceArtifactChart(c *gin.Context) {
	requestId := c.GetString("requestID")

	var body dto.UpdateResourceArtifactChart

	// Unmarshal the request body into the body struct
	if err := c.ShouldBindJSON(&body); err != nil {
		restErr := rest_errors.NewBadRequestError("Invalid request body", err)
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to unmarshal request body", zap.Any("Error", err))
		return
	}

	logger.InfoR(requestId, "Updating resource instance chart with params", zap.Any("body", body))
	service, restErr := ValidateUpdateResourceArtifactChartRequest(body)
	if restErr != nil {
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to validate request", zap.Any("Error", restErr))
		return
	}

	response, err := service.UpdateResourceArtifactChart(requestId, body)
	if err != nil {
		c.JSON(err.Status(), err)
		logger.ErrorR(requestId, "Failed to update resource instance chart", zap.Any("Error", err))
		return
	}

	c.JSON(http.StatusOK, response)
	logger.InfoR(requestId, "Resource instance chart updated successfully", zap.Any("response", response))
}

func UpdateResourceArtifactValues(c *gin.Context) {
	requestId := c.GetString("requestID")

	var body dto.UpdateResourceArtifactValues

	// Unmarshal the request body into the body struct
	if err := c.ShouldBindJSON(&body); err != nil {
		restErr := rest_errors.NewBadRequestError("Invalid request body", err)
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to unmarshal request body", zap.Any("Error", err))
		return
	}

	logger.InfoR(requestId, "Updating resource instance values", zap.Any("body", body))
	service, restErr := ValidateUpdateResourceArtifactValuesRequest(body)
	if restErr != nil {
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to validate request", zap.Any("Error", restErr))
		return
	}

	response, err := service.UpdateResourceArtifactValues(requestId, body)
	if err != nil {
		c.JSON(err.Status(), err)
		logger.ErrorR(requestId, "Failed to update resource instance values", zap.Any("Error", err))
		return
	}

	c.JSON(http.StatusOK, response)
	logger.InfoR(requestId, "Resource instance values updated successfully", zap.Any("response", response))
}

func StartResourceInstance(c *gin.Context) {
	requestId := c.GetString("requestID")

	var body dto.StartResourceInstance

	if err := c.ShouldBindJSON(&body); err != nil {
		restErr := rest_errors.NewBadRequestError("Invalid request body", err)
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to unmarshal request body", zap.Any("Error", err))
		return
	}

	logger.InfoR(requestId, "Starting resource instance", zap.Any("body", body))
	service, restErr := ValidateStartResourceInstanceRequest(body)
	if restErr != nil {
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to validate request", zap.Any("Error", restErr))
		return
	}

	response, err := service.StartResourceInstance(requestId, body)
	if err != nil {
		c.JSON(err.Status(), err)
		logger.ErrorR(requestId, "Failed to start resource instance", zap.Any("Error", err))
		return
	}

	c.JSON(http.StatusAccepted, response)
	logger.InfoR(requestId, "Resource instance started successfully", zap.Any("response", response))
}

func StopResourceInstance(c *gin.Context) {
	requestId := c.GetString("requestID")

	var body dto.StopResourceInstance

	if err := c.ShouldBindJSON(&body); err != nil {
		restErr := rest_errors.NewBadRequestError("Invalid request body", err)
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to unmarshal request body", zap.Any("Error", err))
		return
	}

	logger.InfoR(requestId, "Stopping resource instance", zap.Any("body", body))
	service, restErr := ValidateStopResourceInstanceRequest(body)
	if restErr != nil {
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to validate request", zap.Any("Error", restErr))
		return
	}

	response, err := service.StopResourceInstance(requestId, body)
	if err != nil {
		c.JSON(err.Status(), err)
		logger.ErrorR(requestId, "Failed to stop resource instance", zap.Any("Error", err))
		return
	}

	c.JSON(http.StatusAccepted, response)
	logger.InfoR(requestId, "Resource instance stopped successfully", zap.Any("response", response))
}

func ResourceInstanceStatus(c *gin.Context) {
	requestId := c.GetString("requestID")

	var body dto.ResourceInstanceStatus

	if err := c.ShouldBindJSON(&body); err != nil {
		restErr := rest_errors.NewBadRequestError("Invalid request body", err)
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to unmarshal request body", zap.Any("Error", err))
		return
	}

	logger.InfoR(requestId, "Getting status of resource instance", zap.Any("body", body))
	service, restErr := ValidateResourceInstanceStatusRequest(body)
	if restErr != nil {
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to validate request", zap.Any("Error", restErr))
		return
	}

	response, err := service.ResourceInstanceStatus(requestId, body)
	if err != nil {
		c.JSON(err.Status(), err)
		logger.ErrorR(requestId, "Failed to get status of resource instance", zap.Any("Error", err))
		return
	}

	c.JSON(http.StatusOK, response)
	logger.InfoR(requestId, "Resource instance status retrieved successfully", zap.Any("response", response))
}

func UpdateServiceSelector(c *gin.Context) {
	requestId := c.GetString("requestID")

	var body dto.UpdateServiceSelector

	if err := c.ShouldBindJSON(&body); err != nil {
		restErr := rest_errors.NewBadRequestError("Invalid request body", err)
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to unmarshal request body", zap.Any("Error", err))
		return
	}

	logger.InfoR(requestId, "Updating service selector", zap.Any("body", body))
	service, restErr := ValidateUpdateServiceSelectorRequest(body)
	if restErr != nil {
		c.JSON(restErr.Status(), restErr)
		logger.ErrorR(requestId, "Failed to validate request", zap.Any("Error", restErr))
		return
	}

	response, err := service.UpdateServiceSelector(requestId, body)
	if err != nil {
		c.JSON(err.Status(), err)
		logger.ErrorR(requestId, "Failed to update service selector", zap.Any("Error", err))
		return
	}

	c.JSON(http.StatusOK, response)
	logger.InfoR(requestId, "Service selector updated successfully", zap.Any("response", response))
}
