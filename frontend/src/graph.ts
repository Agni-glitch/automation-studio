import type { Edge, Node } from "@xyflow/react";
import type { Connection, NodeDefinition, NodeStatus, NodeTypeInfo, WorkflowDefinition } from "./types";

export type StudioNodeData = {
  def: NodeDefinition;
  info?: NodeTypeInfo;
  status?: NodeStatus;
};
export type StudioNode = Node<StudioNodeData, "studio">;

export type WorkflowMeta = Omit<WorkflowDefinition, "nodes" | "connections">;

const COL = 250;
const ROW = 120;

/** Left-to-right layout by dependency depth, for workflows saved without positions. */
function autoLayout(wf: WorkflowDefinition): Map<string, { x: number; y: number }> {
  const preds = new Map<string, string[]>(wf.nodes.map((n) => [n.id, []]));
  wf.connections.forEach((c) => preds.get(c.target)?.push(c.source));
  const depth = new Map<string, number>();
  const visit = (id: string, guard = 0): number => {
    if (depth.has(id)) return depth.get(id)!;
    if (guard > wf.nodes.length) return 0; // cycle: let validation report it
    const d = Math.max(-1, ...(preds.get(id) ?? []).map((p) => visit(p, guard + 1))) + 1;
    depth.set(id, d);
    return d;
  };
  wf.nodes.forEach((n) => visit(n.id));
  const perColumn = new Map<number, number>();
  const out = new Map<string, { x: number; y: number }>();
  wf.nodes.forEach((n) => {
    const d = depth.get(n.id) ?? 0;
    const row = perColumn.get(d) ?? 0;
    perColumn.set(d, row + 1);
    out.set(n.id, { x: 80 + d * COL, y: 120 + row * ROW });
  });
  return out;
}

export function edgeId(c: Connection): string {
  return `${c.source}:${c.source_output ?? "main"}->${c.target}`;
}

export function toFlow(wf: WorkflowDefinition, catalog: Map<string, NodeTypeInfo>): { nodes: StudioNode[]; edges: Edge[] } {
  const layout = wf.nodes.some((n) => !n.position) ? autoLayout(wf) : null;
  const nodes: StudioNode[] = wf.nodes.map((def) => ({
    id: def.id,
    type: "studio",
    position: def.position ? { x: def.position[0], y: def.position[1] } : layout!.get(def.id)!,
    data: { def, info: catalog.get(def.type) },
  }));
  const edges: Edge[] = wf.connections.map((c) => makeEdge(c.source, c.target, c.source_output ?? "main"));
  return { nodes, edges };
}

export function makeEdge(source: string, target: string, output: string): Edge {
  return {
    id: edgeId({ source, target, source_output: output }),
    source,
    target,
    sourceHandle: output,
    targetHandle: "in",
    // branch names are drawn next to the node's output handles, so edges stay unlabeled
    className: output === "error" ? "edge-error" : undefined,
  };
}

export function fromFlow(meta: WorkflowMeta, nodes: StudioNode[], edges: Edge[]): WorkflowDefinition {
  return {
    ...meta,
    nodes: nodes.map((n) => ({
      ...n.data.def,
      id: n.id,
      position: [Math.round(n.position.x), Math.round(n.position.y)],
    })),
    connections: edges.map((e) => ({ source: e.source, target: e.target, source_output: e.sourceHandle ?? "main" })),
  };
}

export function newNodeId(type: string, existing: Set<string>): string {
  const base = (type.split(".").pop() ?? "node").replace(/[^A-Za-z0-9_-]/g, "_");
  if (!existing.has(base)) return base;
  let i = 2;
  while (existing.has(`${base}_${i}`)) i++;
  return `${base}_${i}`;
}

export function randomId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export function blankWorkflow(): WorkflowDefinition {
  return {
    id: randomId(),
    name: "Untitled workflow",
    description: "",
    nodes: [{ id: "start", type: "trigger.manual", parameters: {}, credentials: {}, position: [80, 200] }],
    connections: [],
    variables: {},
    settings: {},
  };
}

export const CATEGORY_META: Record<string, { label: string; color: string; icon: string }> = {
  trigger: { label: "Triggers", color: "var(--cat-trigger)", icon: "⚡" },
  ai: { label: "AI", color: "var(--cat-ai)", icon: "✦" },
  code: { label: "Code", color: "var(--cat-code)", icon: "{}" },
  action: { label: "Actions", color: "var(--cat-action)", icon: "➜" },
  logic: { label: "Logic", color: "var(--cat-logic)", icon: "◇" },
};
