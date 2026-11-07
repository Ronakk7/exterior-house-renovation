/**
 * Centralized in-memory reactive state store.
 */

import * as api from "./api.js";

class Store extends EventTarget {
  constructor() {
    super();
    this.state = {
      config: null,
      catalogue: null,
      project: null,
      photos: [],
      components: [],
      variants: [],
      activeVariantId: null,
      generations: [],
      measurements: [],
      rates: [],
      estimate: null,
      reports: [],
    };
  }

  getState(key) {
    return this.state[key];
  }

  setState(key, value) {
    this.state[key] = value;
    this.dispatchEvent(new CustomEvent("change", { detail: { key, value } }));
  }

  resetProject() {
    this.state.project = null;
    this.state.photos = [];
    this.state.components = [];
    this.state.variants = [];
    this.state.activeVariantId = null;
    this.state.generations = [];
    this.state.measurements = [];
    this.state.rates = [];
    this.state.estimate = null;
    this.state.reports = [];
    this.dispatchEvent(new CustomEvent("change", { detail: { key: "project", value: null } }));
  }

  // Refresh helpers
  async refreshProject(projectId) {
    const proj = await api.getProject(projectId);
    this.setState("project", proj);
    this.setState("activeVariantId", proj.active_variant_id);
    return proj;
  }

  async refreshPhotos(projectId) {
    const res = await api.listPhotos(projectId);
    this.setState("photos", res.items || []);
    return this.state.photos;
  }

  async refreshComponents(projectId, photoId = null) {
    const res = await api.listComponents(projectId, photoId);
    this.setState("components", res.items || []);
    return this.state.components;
  }

  async refreshVariants(projectId) {
    const res = await api.listVariants(projectId);
    this.setState("variants", res.items || []);
    return this.state.variants;
  }

  async refreshGenerations(projectId, variantId = null) {
    const res = await api.listGenerations(projectId, variantId);
    this.setState("generations", res.items || []);
    return this.state.generations;
  }

  async refreshMeasurements(projectId) {
    const res = await api.listMeasurements(projectId);
    this.setState("measurements", res.items || []);
    return this.state.measurements;
  }

  async refreshRates(projectId) {
    const res = await api.listRates(projectId);
    this.setState("rates", res.items || []);
    return this.state.rates;
  }

  async refreshEstimate(projectId, variantId) {
    if (!variantId) return null;
    const res = await api.getEstimate(projectId, variantId);
    this.setState("estimate", res);
    return res;
  }

  async refreshReports(projectId) {
    const res = await api.listReports(projectId);
    this.setState("reports", res.items || []);
    return this.state.reports;
  }
}

export const store = new Store();

