import { computed, reactive, readonly } from "vue";
import { STAGES } from "../domain/stages";
import type {
  ComparisonSummary,
  ObservationSummary,
  PlotDetail,
  PlotSummary,
  WorkspaceKey,
} from "../domain/types";
import { api, errorMessage } from "../services/api";

interface Notice {
  id: number;
  tone: "success" | "error" | "info";
  message: string;
}

interface WorkspaceState {
  active: WorkspaceKey;
  loading: boolean;
  plots: PlotSummary[];
  plotDetails: Record<string, PlotDetail>;
  selectedPlotId: string | null;
  observations: ObservationSummary[];
  selectedObservationId: string | null;
  comparisons: ComparisonSummary[];
  selectedComparisonId: string | null;
  notices: Notice[];
  backendOnline: boolean;
}

let noticeSequence = 0;

const state = reactive<WorkspaceState>({
  active: "catalog",
  loading: false,
  plots: [],
  plotDetails: {},
  selectedPlotId: null,
  observations: [],
  selectedObservationId: null,
  comparisons: [],
  selectedComparisonId: null,
  notices: [],
  backendOnline: false,
});

const selectedPlot = computed(() =>
  state.selectedPlotId
    ? state.plotDetails[state.selectedPlotId] ?? null
    : null,
);

const selectedObservation = computed(() =>
  state.observations.find((item) => item.id === state.selectedObservationId) ??
  null,
);

const selectedComparison = computed(() =>
  state.comparisons.find((item) => item.id === state.selectedComparisonId) ??
  null,
);

export function useWorkspace() {
  async function initialize(): Promise<void> {
    state.loading = true;
    try {
      await api.health();
      state.backendOnline = true;
      await Promise.all([
        refreshPlots(),
        refreshObservations(),
        refreshComparisons(),
      ]);
    } catch (error) {
      state.backendOnline = false;
      pushNotice("error", errorMessage(error));
    } finally {
      state.loading = false;
    }
  }

  async function refreshPlots(): Promise<void> {
    const response = (await api.listPlots()) as { items: PlotSummary[] };
    state.plots = response.items;
    if (
      state.selectedPlotId &&
      !state.plots.some((plot) => plot.id === state.selectedPlotId)
    ) {
      state.selectedPlotId = null;
    }
    if (!state.selectedPlotId && state.plots.length > 0) {
      state.selectedPlotId = state.plots[0].id;
      await loadPlot(state.selectedPlotId);
    }
  }

  async function loadPlot(plotId: string): Promise<void> {
    const detail = (await api.getPlot(plotId)) as PlotDetail;
    state.plotDetails[plotId] = detail;
    state.selectedPlotId = plotId;
  }

  async function createPlot(payload: Record<string, unknown>): Promise<PlotSummary> {
    return (await api.createPlot(payload)) as PlotSummary;
  }

  async function createTree(payload: Record<string, unknown>): Promise<void> {
    await api.createTree(payload);
    if (state.selectedPlotId) {
      await loadPlot(state.selectedPlotId);
    }
  }

  async function confirmSelectedPlot(revision: number): Promise<void> {
    if (!state.selectedPlotId) return;
    await api.confirmPlot(state.selectedPlotId, revision);
    await Promise.all([loadPlot(state.selectedPlotId), refreshPlots()]);
  }

  async function refreshObservations(): Promise<void> {
    const response = (await api.listObservations()) as {
      items: ObservationSummary[];
    };
    state.observations = response.items;
    if (
      state.selectedObservationId &&
      !state.observations.some(
        (item) => item.id === state.selectedObservationId,
      )
    ) {
      state.selectedObservationId = null;
    }
  }

  async function startObservation(
    payload: Record<string, unknown>,
  ): Promise<ObservationSummary> {
    const observation = (await api.createObservation(
      payload,
    )) as ObservationSummary;
    state.selectedObservationId = observation.id;
    await refreshObservations();
    return observation;
  }

  async function addStage(
    observation: ObservationSummary,
    payload: Record<string, unknown>,
  ): Promise<ObservationSummary> {
    const updated = (await api.addStage(observation.id, {
      ...payload,
      revision: observation.revision,
    })) as ObservationSummary;
    replaceObservation(updated);
    return updated;
  }

  async function removeStage(
    observation: ObservationSummary,
    stage: string,
  ): Promise<void> {
    const updated = (await api.removeStage(
      observation.id,
      stage,
      observation.revision,
    )) as ObservationSummary;
    replaceObservation(updated);
  }

  async function completeObservation(
    observation: ObservationSummary,
  ): Promise<void> {
    const updated = (await api.completeObservation(
      observation.id,
      observation.revision,
    )) as ObservationSummary;
    replaceObservation(updated);
  }

  async function refreshComparisons(): Promise<void> {
    const response = (await api.listComparisons()) as {
      items: ComparisonSummary[];
    };
    state.comparisons = response.items;
    if (!state.selectedComparisonId && state.comparisons.length > 0) {
      state.selectedComparisonId = state.comparisons[0].id;
    }
  }

  async function createComparison(
    payload: Record<string, unknown>,
  ): Promise<ComparisonSummary> {
    const comparison = (await api.createComparison(
      payload,
    )) as ComparisonSummary;
    state.selectedComparisonId = comparison.id;
    await refreshComparisons();
    return comparison;
  }

  async function createBrief(
    plotId: string,
    title: string,
  ): Promise<unknown> {
    return api.createBrief(plotId, title);
  }

  function replaceObservation(updated: ObservationSummary): void {
    const index = state.observations.findIndex((item) => item.id === updated.id);
    if (index >= 0) {
      state.observations.splice(index, 1, updated);
    } else {
      state.observations.unshift(updated);
    }
  }

  function setActiveWorkspace(key: WorkspaceKey): void {
    state.active = key;
  }

  function selectPlot(plotId: string): void {
    void loadPlot(plotId).catch((error) => {
      pushNotice("error", errorMessage(error));
    });
  }

  function selectObservation(observationId: string): void {
    state.selectedObservationId = observationId;
  }

  function selectComparison(comparisonId: string): void {
    state.selectedComparisonId = comparisonId;
  }

  function pushNotice(
    tone: Notice["tone"],
    message: string,
    ttl = 4200,
  ): void {
    const notice: Notice = {
      id: ++noticeSequence,
      tone,
      message,
    };
    state.notices.push(notice);
    window.setTimeout(() => dismissNotice(notice.id), ttl);
  }

  function dismissNotice(id: number): void {
    const index = state.notices.findIndex((item) => item.id === id);
    if (index >= 0) state.notices.splice(index, 1);
  }

  async function runAction<T>(
    action: () => Promise<T>,
    successMessage: string,
  ): Promise<T | null> {
    state.loading = true;
    try {
      const result = await action();
      pushNotice("success", successMessage);
      return result;
    } catch (error) {
      pushNotice("error", errorMessage(error));
      return null;
    } finally {
      state.loading = false;
    }
  }

  return {
    state: readonly(state),
    selectedPlot,
    selectedObservation,
    selectedComparison,
    stages: STAGES,
    initialize,
    refreshPlots,
    refreshObservations,
    refreshComparisons,
    loadPlot,
    createPlot,
    createTree,
    confirmSelectedPlot,
    startObservation,
    addStage,
    removeStage,
    completeObservation,
    createComparison,
    createBrief,
    setActiveWorkspace,
    selectPlot,
    selectObservation,
    selectComparison,
    pushNotice,
    dismissNotice,
    runAction,
  };
}
