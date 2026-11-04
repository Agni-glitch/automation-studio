import { useState, type JSX } from "react";
import type { JsonSchema } from "../types";
import { CodeEditor, JsonEditor } from "./Editors";

type Kind = "code" | "enum" | "multi" | "bool" | "number" | "text" | "multiline" | "lines" | "any" | "json";

const MULTILINE = new Set(["prompt", "system_prompt", "body", "text", "message"]);
const EXPRESSION = /\{\{.*\}\}/s;

function deref(s: JsonSchema, root: JsonSchema): JsonSchema {
  if (!s.$ref) return s;
  return root.$defs?.[s.$ref.split("/").pop() ?? ""] ?? {};
}

/** Resolve $ref and drop the null branch of Optional[...] fields. */
function unwrap(s: JsonSchema, root: JsonSchema): JsonSchema {
  const base = deref(s, root);
  if (!base.anyOf) return base;
  const branches = base.anyOf.map((b) => deref(b, root)).filter((b) => b.type !== "null");
  if (branches.length === 1) return { ...branches[0], title: base.title ?? branches[0].title, default: base.default ?? branches[0].default };
  return { ...base, anyOf: branches };
}

function kindOf(name: string, s: JsonSchema, root: JsonSchema): Kind {
  if (name === "code") return "code";
  if (s.enum) return "enum";
  const type = Array.isArray(s.type) ? s.type[0] : s.type;
  if (type === "boolean") return "bool";
  if (type === "integer" || type === "number") return "number";
  if (type === "string") return MULTILINE.has(name) ? "multiline" : "text";
  if (type === "array" && s.items) {
    const items = unwrap(s.items, root);
    if (items.enum) return "multi";
    if (items.type === "string") return "lines";
  }
  if (!type && !s.anyOf && !s.properties) return "any";
  return "json";
}

function label(name: string, s: JsonSchema): string {
  return s.title ?? name.replace(/_/g, " ");
}

function parseLoose(text: string): unknown {
  const t = text.trim();
  if (!t) return undefined;
  if (/^(\{|\[|-?\d|true$|false$|null$|")/.test(t)) {
    try {
      return JSON.parse(t);
    } catch {
      /* fall through: keep as text */
    }
  }
  return text;
}

type FieldProps = {
  name: string;
  schema: JsonSchema;
  root: JsonSchema;
  required: boolean;
  value: unknown;
  onChange: (v: unknown) => void;
};

function Field({ name, schema, root, required, value, onChange }: FieldProps) {
  const s = unwrap(schema, root);
  const kind = kindOf(name, s, root);
  const canExpr = ["enum", "multi", "bool", "number", "lines", "json"].includes(kind);
  const [expr, setExpr] = useState(typeof value === "string" && EXPRESSION.test(value) && canExpr);
  const placeholder = s.default !== undefined && s.default !== null ? `default: ${JSON.stringify(s.default)}` : "";

  let input: JSX.Element;
  if (expr) {
    input = (
      <input className="expr" value={typeof value === "string" ? value : value === undefined ? "" : JSON.stringify(value)}
        placeholder="{{ input.field }}" onChange={(e) => onChange(e.target.value || undefined)} />
    );
  } else {
    switch (kind) {
      case "code":
        input = <CodeEditor value={typeof value === "string" ? value : ""} onChange={(v) => onChange(v || undefined)} />;
        break;
      case "enum":
        input = (
          <select value={value === undefined ? "" : String(value)} onChange={(e) => {
            const raw = e.target.value;
            onChange(raw === "" ? undefined : s.enum!.find((o) => String(o) === raw));
          }}>
            <option value="">{s.default !== undefined ? `${String(s.default)} (default)` : "—"}</option>
            {s.enum!.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
          </select>
        );
        break;
      case "multi": {
        const options = unwrap(s.items!, root).enum ?? [];
        const current = Array.isArray(value) ? value : ((s.default as unknown[]) ?? []);
        input = (
          <div className="checks">
            {options.map((o) => (
              <label key={String(o)} className="check">
                <input type="checkbox" checked={current.includes(o)} onChange={(e) =>
                  onChange(e.target.checked ? [...current, o] : current.filter((x) => x !== o))} />
                {String(o)}
              </label>
            ))}
          </div>
        );
        break;
      }
      case "bool": {
        const checked = value === undefined ? Boolean(s.default) : Boolean(value);
        input = (
          <label className="check">
            <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
            {checked ? "yes" : "no"}
          </label>
        );
        break;
      }
      case "number":
        input = (
          <input inputMode="decimal" value={value === undefined ? "" : String(value)} placeholder={placeholder}
            onChange={(e) => {
              const raw = e.target.value.trim();
              onChange(raw === "" ? undefined : /^-?\d+(\.\d+)?$/.test(raw) ? Number(raw) : raw);
            }} />
        );
        break;
      case "multiline":
        input = <textarea rows={name === "body" || name === "prompt" ? 6 : 3} value={(value as string) ?? ""}
          placeholder={placeholder} onChange={(e) => onChange(e.target.value || undefined)} />;
        break;
      case "lines":
        input = (
          <textarea rows={3} placeholder={placeholder || "one per line"}
            value={Array.isArray(value) ? value.join("\n") : typeof value === "string" ? value : ""}
            onChange={(e) => {
              const items = e.target.value.split("\n").map((x) => x.trim()).filter(Boolean);
              onChange(items.length ? items : undefined);
            }} />
        );
        break;
      case "any":
        input = (
          <textarea rows={typeof value === "object" && value !== null ? 4 : 1} placeholder={placeholder || "text, number, JSON or {{ expression }}"}
            defaultValue={value === undefined ? "" : typeof value === "string" ? value : JSON.stringify(value, null, 2)}
            onChange={(e) => onChange(parseLoose(e.target.value))} />
        );
        break;
      case "json":
        input = <JsonEditor value={value} onChange={onChange} height={name === "steps" ? "240px" : "120px"} />;
        break;
      default:
        input = <input value={(value as string) ?? ""} placeholder={placeholder} spellCheck={false}
          onChange={(e) => onChange(e.target.value || undefined)} />;
    }
  }

  return (
    <div className="field">
      <div className="field-label">
        <span>{label(name, s)}{required && <span className="req">*</span>}</span>
        {canExpr && (
          <button type="button" className={`fx ${expr ? "on" : ""}`} title="Use an expression like {{ input.x }}"
            onClick={() => setExpr(!expr)}>fx</button>
        )}
      </div>
      {input}
      {s.description && <div className="hint">{s.description}</div>}
    </div>
  );
}

export default function SchemaForm({
  schema,
  value,
  onChange,
}: {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const names = Object.keys(props).sort((a, b) => Number(required.has(b)) - Number(required.has(a)));
  if (!names.length) return <div className="muted">This node has no parameters.</div>;
  return (
    <div className="form">
      {names.map((name) => (
        <Field key={name} name={name} schema={props[name]} root={schema} required={required.has(name)}
          value={value[name]}
          onChange={(v) => {
            const next = { ...value };
            if (v === undefined) delete next[name];
            else next[name] = v;
            onChange(next);
          }} />
      ))}
    </div>
  );
}
