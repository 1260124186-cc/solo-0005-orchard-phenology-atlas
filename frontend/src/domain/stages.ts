import type { StageDefinition, StageEntry } from "./types";

export const STAGES: StageDefinition[] = [
  {
    key: "bud_swell",
    label: "芽膨大期",
    rank: 10,
    required_for_completion: false,
  },
  {
    key: "bud_burst",
    label: "萌芽期",
    rank: 20,
    required_for_completion: true,
  },
  {
    key: "first_bloom",
    label: "初花期",
    rank: 30,
    required_for_completion: false,
  },
  {
    key: "full_bloom",
    label: "盛花期",
    rank: 40,
    required_for_completion: true,
  },
  {
    key: "petal_fall",
    label: "落瓣期",
    rank: 50,
    required_for_completion: false,
  },
  {
    key: "fruit_set",
    label: "坐果期",
    rank: 60,
    required_for_completion: true,
  },
  {
    key: "fruit_growth",
    label: "果实膨大期",
    rank: 70,
    required_for_completion: false,
  },
  {
    key: "harvest",
    label: "采收期",
    rank: 80,
    required_for_completion: true,
  },
  {
    key: "leaf_fall",
    label: "落叶期",
    rank: 90,
    required_for_completion: false,
  },
];

export const STAGE_BY_KEY = Object.fromEntries(
  STAGES.map((stage) => [stage.key, stage]),
) as Record<string, StageDefinition>;

export const REQUIRED_STAGE_KEYS = STAGES.filter(
  (stage) => stage.required_for_completion,
).map((stage) => stage.key);

export function stageLabel(key: string): string {
  return STAGE_BY_KEY[key]?.label ?? key;
}

export function sortStageEntries(entries: StageEntry[]): StageEntry[] {
  return [...entries].sort((left, right) => {
    const rank =
      (STAGE_BY_KEY[left.stage]?.rank ?? 999) -
      (STAGE_BY_KEY[right.stage]?.rank ?? 999);
    if (rank !== 0) return rank;
    return left.observed_on.localeCompare(right.observed_on);
  });
}

export function completedProgress(entries: readonly StageEntry[]): number {
  const present = new Set(entries.map((entry) => entry.stage));
  const completed = REQUIRED_STAGE_KEYS.filter((key) => present.has(key)).length;
  return Math.round((completed / REQUIRED_STAGE_KEYS.length) * 100);
}
