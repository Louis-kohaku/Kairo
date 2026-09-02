export interface ProductionStep {
  id: string;
  label: string;
}

interface Props {
  steps: ProductionStep[];
  currentId: string;
  doneIds: Set<string>;
  onSelect: (id: string) => void;
}

export default function StepBar({ steps, currentId, doneIds, onSelect }: Props) {
  return (
    <div className="step-bar">
      {steps.map((step, i) => {
        const isDone = doneIds.has(step.id);
        const isCurrent = step.id === currentId;
        const state = isCurrent ? "current" : isDone ? "done" : "pending";
        return (
          <div className="step-bar-item" key={step.id}>
            <button
              className={`step-bar-node step-bar-node-${state}`}
              onClick={() => onSelect(step.id)}
              title={step.label}
            >
              <span className="step-bar-mark">{isCurrent ? "●" : isDone ? "✓" : "○"}</span>
              <span className="step-bar-index">{i + 1}</span>
              <span className="step-bar-label">{step.label}</span>
            </button>
            {i < steps.length - 1 && (
              <span className={`step-bar-arrow${isDone ? " step-bar-arrow-done" : ""}`}>→</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
