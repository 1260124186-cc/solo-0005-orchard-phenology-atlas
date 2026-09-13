import { STAGE_BY_KEY } from "./stages";
import type { ObservationSummary, PlotSummary, StageEntry, TreeRecord } from "./types";

export interface FieldIssue {
  field: string;
  message: string;
}

export function validatePlotDraft(plot: Partial<PlotSummary>): FieldIssue[] {
  const issues: FieldIssue[] = [];
  const code = String(plot.code ?? "").trim().toUpperCase();
  if (!/^[A-Z]{2,6}-\d{3,4}$/.test(code)) {
    issues.push({
      field: "code",
      message: "园区编号应为两个到六个字母、连字符和三到四位数字",
    });
  }
  if (!String(plot.name ?? "").trim()) {
    issues.push({ field: "name", message: "请填写园区名称" });
  }
  if (!String(plot.locality ?? "").trim()) {
    issues.push({ field: "locality", message: "请填写地点描述" });
  }
  if (!String(plot.cultivar_focus ?? "").trim()) {
    issues.push({ field: "cultivar_focus", message: "请填写重点品种" });
  }
  if (!String(plot.steward ?? "").trim()) {
    issues.push({ field: "steward", message: "请填写档案责任人或机构" });
  }
  const year = Number(plot.planting_year);
  if (!Number.isInteger(year) || year < 1800 || year > new Date().getFullYear() + 2) {
    issues.push({ field: "planting_year", message: "起始种植年份超出范围" });
  }
  return issues;
}

export function validateTreeDraft(tree: Partial<TreeRecord>): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (!String(tree.code ?? "").trim()) {
    issues.push({ field: "code", message: "请填写植株编号" });
  }
  if (!String(tree.cultivar ?? "").trim()) {
    issues.push({ field: "cultivar", message: "请填写品种名" });
  }
  const year = Number(tree.planting_year);
  if (!Number.isInteger(year) || year < 1800) {
    issues.push({ field: "planting_year", message: "请填写有效定植年份" });
  }
  return issues;
}

export function validateStageDraft(
  entry: Partial<StageEntry>,
  existing: readonly StageEntry[],
): FieldIssue[] {
  const issues: FieldIssue[] = [];
  if (!entry.stage || !STAGE_BY_KEY[entry.stage]) {
    issues.push({ field: "stage", message: "请选择物候阶段" });
  }
  if (!entry.observed_on || !/^\d{4}-\d{2}-\d{2}$/.test(entry.observed_on)) {
    issues.push({ field: "observed_on", message: "请选择观察日期" });
  }
  if (existing.some((item) => item.stage === entry.stage)) {
    issues.push({ field: "stage", message: "该阶段已经存在" });
  }
  const confidence = Number(entry.confidence);
  if (!Number.isInteger(confidence) || confidence < 1 || confidence > 5) {
    issues.push({ field: "confidence", message: "置信度须在 1 到 5 之间" });
  }
  if (entry.observed_on) {
    const candidate = [...existing, entry as StageEntry]
      .filter((item) => STAGE_BY_KEY[item.stage])
      .sort(
        (left, right) =>
          STAGE_BY_KEY[left.stage].rank - STAGE_BY_KEY[right.stage].rank,
      );
    for (let index = 1; index < candidate.length; index += 1) {
      const previous = candidate[index - 1];
      const current = candidate[index];
      if (current.observed_on < previous.observed_on) {
        issues.push({
          field: "observed_on",
          message: `${STAGE_BY_KEY[current.stage].label}不能早于${STAGE_BY_KEY[previous.stage].label}`,
        });
        break;
      }
    }
  }
  return issues;
}

export function missingRequiredStages(observation: ObservationSummary): string[] {
  const present = new Set(observation.entries.map((entry) => entry.stage));
  return Object.values(STAGE_BY_KEY)
    .filter((stage) => stage.required_for_completion && !present.has(stage.key))
    .map((stage) => stage.label);
}

export function canCompareObservations(
  left: Pick<ObservationSummary, "id" | "status" | "season" | "entries"> | null,
  right: Pick<ObservationSummary, "id" | "status" | "season" | "entries"> | null,
): boolean {
  if (!left || !right || left.id === right.id) return false;
  if (left.status !== "completed" || right.status !== "completed") return false;
  if (left.season !== right.season) return false;
  const leftStages = new Set(left.entries.map((entry) => entry.stage));
  return right.entries.some((entry) => leftStages.has(entry.stage));
}

export function formatOffset(value: number): string {
  if (value === 0) return "同日";
  return value > 0 ? `晚 ${value} 天` : `早 ${Math.abs(value)} 天`;
}

export function formatTimestamp(value: string | null): string {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
