// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import archiveJson from "../../docs/experiments/engine-evaluation-2026-11-08/showcase.json";
import { Showcase } from "./Showcase";
import {
  filterCases,
  pairOverview,
  solutionLabel,
  jobStateLabel,
} from "./model";
import type { Archive } from "./model";

const archive = archiveJson as unknown as Archive;
const roots: ReturnType<typeof createRoot>[] = [];
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
afterEach(() => {
  roots.forEach((root) => act(() => root.unmount()));
  roots.length = 0;
  document.body.innerHTML = "";
});
function mount() {
  const node = document.createElement("div");
  document.body.append(node);
  const root = createRoot(node);
  roots.push(root);
  act(() => root.render(<Showcase archive={archive} />));
  return node;
}
function select(node: HTMLElement, value: string) {
  const select = node.querySelector("select")!;
  act(() => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
describe("독립 공개 아카이브", () => {
  it("전체 평가와 선택 범위, 원시 검사 상태와 별도 감사를 구분한다", () => {
    const html = renderToStaticMarkup(<Showcase archive={archive} />);
    expect(contextText(archive)).toContain("35 / 40");
    expect(html).toContain("80회");
    expect(html).toContain("20쌍");
    expect(html).toContain("40개 기록 표시");
    expect(html).toContain("not_run");
    expect(html).toContain("별도 독립 감사");
    expect(html).toContain("읽기 전용");
    expect(html).toContain("+34분");
    expect(html).toContain("-4건");
    expect(html).not.toContain("undefined");
  });
  it("검색은 모든 사례와 불리한 50건 사례를 찾으며 결과가 없을 때 명확히 표시한다", () => {
    expect(filterCases(archive.cases, "50건").map((c) => c.case_id)).toEqual([
      "eval_cutoff_50_404",
    ]);
    expect(filterCases(archive.cases, "고정")).toHaveLength(2);
    const node = mount();
    const input = node.querySelector("input")!;
    expect(input.labels?.[0].textContent).toBe("사례 검색");
    expect(node.querySelector("select")!.labels?.[0].textContent).toBe(
      "사례 선택",
    );
    act(() => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "없는사례");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(node.querySelector("[role=status]")?.textContent).toContain(
      "일치하는 사례가 없습니다",
    );
  });
  it("작업 집합이 다른 사례는 경고하고 고정 위험과 실제 미처리 사유를 보존한다", () => {
    const node = mount();
    select(node, "eval_fixed_8_101");
    expect(node.textContent).toContain("처리한 작업 ID 집합이 다릅니다");
    expect(node.textContent).toContain("FIXED_RESIDUAL_RISK");
    expect(node.textContent).toContain("고정 · 출발(departed)");
    const b2 = Array.from(node.querySelectorAll("button")).find((b) =>
      b.textContent?.startsWith("B2"),
    )!;
    act(() => b2.click());
    expect(b2.getAttribute("aria-pressed")).toBe("true");
    expect(node.querySelector("caption")?.textContent).toContain("B2와 B3");
    expect(node.textContent).toContain("원시 검사 상태 not_run");
  });
  it("URL의 API·지도 요청을 무시하고 조회·승인·실행 제어를 제공하지 않는다", () => {
    window.history.replaceState(
      {},
      "",
      "/demo/?mode=http&view=map&api=http://example.invalid&run=R999",
    );
    const node = mount();
    select(node, "eval_cutoff_50_404");
    expect(node.textContent).toContain("0건");
    expect(node.textContent).toContain("FEASIBLE");
    expect(node.querySelector("iframe, form, script, a")).toBeNull();
    expect(
      Array.from(node.querySelectorAll("button")).map((b) =>
        b.textContent?.slice(0, 2),
      ),
    ).toEqual(["B0", "B1", "B2", "B3"]);
  });
});

function contextText(value: Archive) {
  const node = document.createElement("div");
  node.innerHTML = renderToStaticMarkup(<Showcase archive={value} />);
  return node.querySelector('[aria-labelledby="evaluation-title"]')!
    .textContent!;
}
describe("보존 자료에서 계산하는 요약", () => {
  it("실제 비교쌍의 변경·이동·시드·분모가 바뀌면 표시도 바뀐다", () => {
    const changed = structuredClone(archive);
    changed.cases = changed.cases.slice(0, 9);
    changed.context.summary.objective_proven = 3;
    const base = {
      ...changed.context.pairs[0],
      identical_assigned_set: true,
      equal_count_comparable: true,
    };
    changed.context.pairs = [
      { ...base, seed: 0, changed_delta: 9, travel_minutes_delta: 0 },
      { ...base, seed: 11, changed_delta: -2, travel_minutes_delta: null },
      { ...base, seed: 33, changed_delta: null, travel_minutes_delta: -10 },
      {
        ...base,
        seed: 33,
        identical_assigned_set: false,
        changed_delta: 999,
        travel_minutes_delta: 999,
      },
    ];
    const text = contextText(changed);
    expect(text).toContain("입력 9종 · 비교 기록의 계산 시드 3종");
    expect(text).toContain("3 / 8");
    expect(text).toContain("8건 입력: 동일 작업 비교 3 / 4쌍");
    expect(text).toContain("변경 차이(건) -2 ~ +9 (미제공 1쌍)");
    expect(text).toContain("가변 이동 차이(분) -10 ~ 0 (미제공 1쌍)");
    expect(text).not.toContain("999");
    expect(text).not.toContain("12~82");
  });
  it("처리 수 또는 처리 집합이 다른 쌍을 범위에서 제외한다", () => {
    const changed = structuredClone(archive);
    changed.context.pairs = changed.context.pairs
      .slice(0, 2)
      .map((pair, index) => ({
        ...pair,
        equal_count_comparable: index === 0,
        identical_assigned_set: index !== 0,
        changed_delta: 999,
        travel_minutes_delta: 999,
      }));
    const group = pairOverview(changed).groups[0];
    expect(group).toMatchObject({
      comparable: 0,
      total: 2,
      changed: { range: "미제공", unavailable: 0 },
    });
    expect(contextText(changed)).toContain("동일 작업 비교 0 / 2쌍");
    expect(contextText(changed)).not.toContain("999");
  });
  it("빈 비교·누락값을 0으로 만들지 않고 미제공 수와 미확인 규모를 표시한다", () => {
    const changed = structuredClone(archive);
    changed.context.pairs = [];
    expect(contextText(changed)).toContain("계산 시드 0종");
    expect(contextText(changed)).toContain("비교 기록 없음");
    expect(contextText(changed)).toContain("비교 기록이 없습니다");
    expect(contextText(changed)).toContain("변경 차이(건) 미제공");
    const base = archive.context.pairs[0];
    changed.context.pairs = [
      { ...base, changed_delta: null, travel_minutes_delta: null },
      { ...base, case_id: "missing-case" },
    ];
    expect(contextText(changed)).toContain("변경 차이(건) 미제공 (미제공 1쌍)");
    expect(contextText(changed)).toContain("입력 규모 미확인 1쌍");
  });
});
it("최적성 집계가 분모와 불일치하면 비율 대신 자료 확인을 안내한다", () => {
  const changed = structuredClone(archive);
  changed.context.pairs = changed.context.pairs.slice(0, 4);
  for (const invalid of [35, -1, 0.5, Infinity, NaN]) {
    changed.context.summary.objective_proven = invalid;
    const text = contextText(changed);
    expect(text).toContain("자료 불일치 · 원본 확인 필요");
    expect(text).not.toContain("35 / 8");
    expect(text).not.toContain("비교 기록 없음");
  }
  changed.context.summary.objective_proven = 0;
  expect(contextText(changed)).toContain("0 / 8");
  changed.context.summary.objective_proven = 8;
  expect(contextText(changed)).toContain("8 / 8");
  changed.context.pairs = [];
  expect(contextText(changed)).toContain("비교 기록 없음");
  expect(contextText(changed)).not.toContain("자료 불일치");
});

describe("업무 상태의 한국어와 원문 표기", () => {
  it("작업 상태와 모든 해 상태를 한국어로 설명하고 원문을 유지한다", () => {
    expect(jobStateLabel("planned")).toBe("계획(planned)");
    expect(jobStateLabel("departed")).toBe("출발(departed)");
    expect(solutionLabel("BASELINE", false)).toBe("원안(BASELINE)");
    expect(solutionLabel("FEASIBLE", false)).toBe(
      "실행 가능 · 최적 미증명(FEASIBLE)",
    );
    expect(solutionLabel("OPTIMAL", false)).toBe(
      "최적 상태 · 전체 목적 최적 미증명(OPTIMAL)",
    );
    expect(solutionLabel("OPTIMAL", true)).toBe("최적(OPTIMAL)");
    expect(solutionLabel("HEURISTIC", false)).toBe("휴리스틱(HEURISTIC)");
    expect(solutionLabel("INFEASIBLE", false)).toBe("실행 불가능(INFEASIBLE)");
    expect(solutionLabel("UNKNOWN", false)).toBe("해 상태 미확인(UNKNOWN)");
    expect(solutionLabel("MODEL_INVALID", false)).toBe(
      "모델 오류(MODEL_INVALID)",
    );
    expect(solutionLabel("INPUT_INCOMPLETE", false)).toBe(
      "입력 부족(INPUT_INCOMPLETE)",
    );
  });
  it("화면에도 해 상태 설명과 계획 상태를 적용한다", () => {
    const html = renderToStaticMarkup(<Showcase archive={archive} />);
    expect(html).toContain("원안(BASELINE)");
    expect(html).toContain("계획(planned)");
    expect(html).toContain("최적(OPTIMAL)");
  });
});
