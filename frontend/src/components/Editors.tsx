import { json } from "@codemirror/lang-json";
import { python } from "@codemirror/lang-python";
import { oneDark } from "@codemirror/theme-one-dark";
import CodeMirror from "@uiw/react-codemirror";
import { useEffect, useState } from "react";

const PY = [python()];
const JSON_EXT = [json()];
const SETUP = { foldGutter: false, highlightActiveLine: true, autocompletion: true };

export function CodeEditor({ value, onChange, height = "280px" }: { value: string; onChange: (v: string) => void; height?: string }) {
  return (
    <div className="code-editor">
      <CodeMirror value={value} height={height} theme={oneDark} extensions={PY} basicSetup={SETUP} onChange={onChange} />
    </div>
  );
}

/** JSON editor that only reports values that parse; shows the parse error otherwise. */
export function JsonEditor({
  value,
  onChange,
  height = "140px",
}: {
  value: unknown;
  onChange: (v: unknown) => void;
  height?: string;
}) {
  const format = (v: unknown) => (v === undefined ? "" : JSON.stringify(v, null, 2));
  const [text, setText] = useState(format(value));
  const [error, setError] = useState<string | null>(null);

  // external change (e.g. undo, another node) -> resync unless the user is mid-edit with an error
  useEffect(() => {
    if (!error) setText(format(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <div className="code-editor">
      <CodeMirror
        value={text}
        height={height}
        theme={oneDark}
        extensions={JSON_EXT}
        basicSetup={{ ...SETUP, lineNumbers: false }}
        onChange={(t) => {
          setText(t);
          if (!t.trim()) {
            setError(null);
            onChange(undefined);
            return;
          }
          try {
            const parsed = JSON.parse(t);
            setError(null);
            onChange(parsed);
          } catch (e) {
            setError((e as Error).message);
          }
        }}
      />
      {error && <div className="field-error">Invalid JSON: {error}</div>}
    </div>
  );
}

export function ReadonlyJson({ value }: { value: unknown }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return <pre className="json-view">{text ?? "null"}</pre>;
}
