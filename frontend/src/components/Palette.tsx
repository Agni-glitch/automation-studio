import { useMemo, useState } from "react";
import { CATEGORY_META } from "../graph";
import type { NodeTypeInfo } from "../types";

export const DRAG_MIME = "application/x-studio-node";
const ORDER = ["trigger", "ai", "code", "action", "logic"];

export default function Palette({ catalog, onAdd }: { catalog: NodeTypeInfo[]; onAdd: (type: string) => void }) {
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const hits = catalog.filter(
      (n) => !q || n.display_name.toLowerCase().includes(q) || n.type.includes(q) || n.description.toLowerCase().includes(q),
    );
    return ORDER.map((cat) => ({ cat, items: hits.filter((n) => n.category === cat) })).filter((g) => g.items.length);
  }, [catalog, query]);

  return (
    <div className="palette">
      <input className="search" placeholder="Search nodes…" value={query} onChange={(e) => setQuery(e.target.value)} />
      {groups.map(({ cat, items }) => (
        <div key={cat} className="palette-group">
          <div className="palette-heading">{CATEGORY_META[cat].label}</div>
          {items.map((n) => (
            <button
              key={n.type}
              className="palette-item"
              style={{ ["--cat" as string]: CATEGORY_META[cat].color }}
              title={`${n.description}\n\nClick to add, or drag onto the canvas.`}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(DRAG_MIME, n.type);
                e.dataTransfer.effectAllowed = "move";
              }}
              onClick={() => onAdd(n.type)}
            >
              <span className="palette-icon">{CATEGORY_META[cat].icon}</span>
              <span>{n.display_name}</span>
            </button>
          ))}
        </div>
      ))}
      {!groups.length && <div className="muted pad">No nodes match.</div>}
    </div>
  );
}
