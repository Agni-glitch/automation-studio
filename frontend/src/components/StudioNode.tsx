import { Handle, Position, type NodeProps } from "@xyflow/react";
import { memo } from "react";
import { CATEGORY_META, type StudioNode } from "../graph";

const STATUS_LABEL: Record<string, string> = {
  pending: "pending",
  running: "running",
  success: "✓",
  failed: "failed",
  skipped: "skipped",
  cancelled: "cancelled",
};

function StudioNodeView({ id, data, selected }: NodeProps<StudioNode>) {
  const { def, info, status } = data;
  const cat = CATEGORY_META[info?.category ?? "logic"];
  const outputs = [...(info?.outputs ?? ["main"])];
  if (def.on_error === "error_output") outputs.push("error");
  const multi = outputs.length > 1;

  const classes = ["snode", selected && "selected", status && `st-${status}`, def.disabled && "disabled", !info && "unknown"];
  return (
    <div className={classes.filter(Boolean).join(" ")} style={{ ["--cat" as string]: cat.color }}>
      {!info?.is_trigger && <Handle type="target" position={Position.Left} id="in" className="handle-in" />}
      <div className="snode-icon" aria-hidden>{cat.icon}</div>
      <div className="snode-body">
        <div className="snode-title">{def.name || id}</div>
        <div className="snode-type">{info ? info.display_name : `unknown: ${def.type}`}</div>
      </div>
      {status && <div className={`snode-status st-${status}`}>{STATUS_LABEL[status]}</div>}
      {def.disabled && <div className="snode-flag">off</div>}
      {outputs.map((out, i) => {
        const top = `${((i + 1) / (outputs.length + 1)) * 100}%`;
        return (
          <div key={out}>
            <Handle type="source" position={Position.Right} id={out} style={{ top }}
              className={out === "error" ? "handle-error" : undefined} />
            {multi && <span className="handle-label" style={{ top }}>{out}</span>}
          </div>
        );
      })}
    </div>
  );
}

export default memo(StudioNodeView);
