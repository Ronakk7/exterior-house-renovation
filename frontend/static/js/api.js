/**
 * HTTP API Client with centralized error normalization and timeout handling.
 */

export class ApiError extends Error {
  constructor(code, message, details = {}, requestId = null, status = 500) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.status = status;
  }
}

async function request(endpoint, options = {}, timeoutMs = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const defaultHeaders = {
    Accept: "application/json",
  };

  // Only set Content-Type if not sending FormData
  if (!(options.body instanceof FormData)) {
    defaultHeaders["Content-Type"] = "application/json";
  }

  const config = {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options.headers,
    },
    signal: controller.signal,
  };

  try {
    const response = await fetch(endpoint, config);
    clearTimeout(timer);

    const reqId = response.headers.get("X-Request-ID");

    if (response.status === 204) {
      return null;
    }

    let data;
    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      data = await response.text();
    }

    if (!response.ok) {
      const err = data?.error || {};
      throw new ApiError(
        err.code || "API_ERROR",
        err.message || `Request failed with status ${response.status}`,
        err.details || {},
        err.request_id || reqId,
        response.status
      );
    }

    return data;
  } catch (err) {
    clearTimeout(timer);
    if (err instanceof ApiError) {
      throw err;
    }
    if (err.name === "AbortError") {
      throw new ApiError(
        "CLIENT_TIMEOUT",
        "This is taking longer than expected. Please try again.",
        {},
        null,
        408
      );
    }
    throw new ApiError(
      "NETWORK_ERROR",
      "Could not reach the server. Check your connection and try again.",
      {},
      null,
      0
    );
  }
}

// 1. System
export const getHealth = () => request("/api/health");
export const getClientConfig = () => request("/api/client-config");

// 2. Projects
export const createProject = (data) =>
  request("/api/projects", { method: "POST", body: JSON.stringify(data) });

export const listProjects = (limit = 50, offset = 0) =>
  request(`/api/projects?limit=${limit}&offset=${offset}`);

export const getProject = (id) => request(`/api/projects/${id}`);

export const updateProject = (id, data) =>
  request(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(data) });

export const deleteProject = (id) =>
  request(`/api/projects/${id}`, { method: "DELETE" });

// 3. Photos
export const uploadPhoto = (projectId, file, onProgress = () => {}) =>
  new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${projectId}/photos`);
    xhr.timeout = 60000;
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      const requestId = xhr.getResponseHeader("X-Request-ID");
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(new ApiError("API_ERROR", "The server returned an invalid response.", {}, requestId, xhr.status));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        const err = data?.error || {};
        reject(new ApiError(
          err.code || "API_ERROR",
          err.message || `Request failed with status ${xhr.status}`,
          err.details || {},
          err.request_id || requestId,
          xhr.status
        ));
        return;
      }
      resolve(data);
    });
    xhr.addEventListener("error", () => reject(new ApiError(
      "NETWORK_ERROR",
      "Could not reach the server. Check your connection and try again.",
      {},
      null,
      0
    )));
    xhr.addEventListener("timeout", () => reject(new ApiError(
      "CLIENT_TIMEOUT",
      "This upload is taking longer than expected. Please try again.",
      {},
      null,
      408
    )));
    xhr.send(formData);
  });

export const listPhotos = (projectId) =>
  request(`/api/projects/${projectId}/photos`);

export const getPhotoImageUrl = (projectId, photoId) =>
  `/api/projects/${projectId}/photos/${photoId}/image`;

export const deletePhoto = (projectId, photoId) =>
  request(`/api/projects/${projectId}/photos/${photoId}`, { method: "DELETE" });

// 4. Detection (75s timeout)
export const detectComponents = (projectId, photoId) =>
  request(`/api/projects/${projectId}/photos/${photoId}/detect`, { method: "POST" }, 75000);

// 5. Components
export const listComponents = (projectId, photoId = null) => {
  const query = photoId ? `?photo_id=${encodeURIComponent(photoId)}` : "";
  return request(`/api/projects/${projectId}/components${query}`);
};

export const createComponent = (projectId, data) =>
  request(`/api/projects/${projectId}/components`, { method: "POST", body: JSON.stringify(data) });

export const updateComponent = (projectId, componentId, data) =>
  request(`/api/projects/${projectId}/components/${componentId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteComponent = (projectId, componentId) =>
  request(`/api/projects/${projectId}/components/${componentId}`, { method: "DELETE" });

// 6. Catalogue
export const getCatalogue = () => request("/api/catalogue");

export const getMaterials = (componentType = null) => {
  const query = componentType ? `?component_type=${encodeURIComponent(componentType)}` : "";
  return request(`/api/catalogue/materials${query}`);
};

// 7. Variants & Selections
export const listVariants = (projectId) =>
  request(`/api/projects/${projectId}/variants`);

export const createVariant = (projectId, data) =>
  request(`/api/projects/${projectId}/variants`, { method: "POST", body: JSON.stringify(data) });

export const updateVariant = (projectId, variantId, data) =>
  request(`/api/projects/${projectId}/variants/${variantId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteVariant = (projectId, variantId) =>
  request(`/api/projects/${projectId}/variants/${variantId}`, { method: "DELETE" });

export const setSelection = (projectId, variantId, componentId, data) =>
  request(`/api/projects/${projectId}/variants/${variantId}/selections/${componentId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const removeSelection = (projectId, variantId, componentId) =>
  request(`/api/projects/${projectId}/variants/${variantId}/selections/${componentId}`, {
    method: "DELETE",
  });

// 8. Generations (135s timeout)
export const createGeneration = (projectId, variantId, data) =>
  request(
    `/api/projects/${projectId}/variants/${variantId}/generations`,
    { method: "POST", body: JSON.stringify(data) },
    135000
  );

export const listGenerations = (projectId, variantId = null) => {
  const query = variantId ? `?variant_id=${encodeURIComponent(variantId)}` : "";
  return request(`/api/projects/${projectId}/generations${query}`);
};

export const getGeneration = (projectId, generationId) =>
  request(`/api/projects/${projectId}/generations/${generationId}`);

export const approveGeneration = (projectId, generationId, data) =>
  request(`/api/projects/${projectId}/generations/${generationId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });

export const deleteGeneration = (projectId, generationId) =>
  request(`/api/projects/${projectId}/generations/${generationId}`, { method: "DELETE" });

export const getGenerationImageUrl = (projectId, generationId) =>
  `/api/projects/${projectId}/generations/${generationId}/image`;

// 9. Measurements & Rates
export const listMeasurements = (projectId) =>
  request(`/api/projects/${projectId}/measurements`);

export const setMeasurement = (projectId, componentId, data) =>
  request(`/api/projects/${projectId}/components/${componentId}/measurement`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const deleteMeasurement = (projectId, componentId) =>
  request(`/api/projects/${projectId}/components/${componentId}/measurement`, { method: "DELETE" });

export const requestAIEstimate = (projectId, data) =>
  request(`/api/projects/${projectId}/measurements/ai-estimate`, {
    method: "POST",
    body: JSON.stringify(data),
  }, 75000);

export const listRates = (projectId) =>
  request(`/api/projects/${projectId}/rates`);

export const setRate = (projectId, materialId, data) =>
  request(`/api/projects/${projectId}/rates/${materialId}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });

export const resetRate = (projectId, materialId) =>
  request(`/api/projects/${projectId}/rates/${materialId}`, { method: "DELETE" });

export const getEstimate = (projectId, variantId) =>
  request(`/api/projects/${projectId}/variants/${variantId}/estimate`);

// 10. Reports
export const createReport = (projectId, data) =>
  request(`/api/projects/${projectId}/reports`, { method: "POST", body: JSON.stringify(data) });

export const listReports = (projectId) =>
  request(`/api/projects/${projectId}/reports`);

export const getReportDownloadUrl = (projectId, reportId) =>
  `/api/projects/${projectId}/reports/${reportId}/download`;

// 11. Debug stage runs
export const listStageRuns = (projectId, stage = null) => {
  const query = stage ? `?stage=${encodeURIComponent(stage)}` : "";
  return request(`/api/projects/${projectId}/stage-runs${query}`);
};
