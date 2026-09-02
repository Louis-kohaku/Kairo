import type { KeyboardEvent, ReactNode } from "react";

interface Props {
  title: string;
  description?: string;
  selected: boolean;
  disabled?: boolean;
  onSelect: () => void;
  icon?: ReactNode;
  badge?: string;
}

// Shared card-shaped choice control (design doc section 26): selection is
// shown with a checkmark + border-weight change, never color alone, and is
// fully keyboard operable (Tab to focus, Enter/Space to choose) so it reads
// correctly to screen readers as a radio-style option, not a decorative div.
export default function SelectCard({
  title,
  description,
  selected,
  disabled = false,
  onSelect,
  icon,
  badge,
}: Props) {
  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect();
    }
  };

  return (
    <div
      className={`select-card${selected ? " select-card-selected" : ""}${disabled ? " select-card-disabled" : ""}`}
      role="radio"
      aria-checked={selected}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && onSelect()}
      onKeyDown={handleKeyDown}
    >
      {selected && (
        <span className="select-card-check" aria-hidden="true">
          ✓
        </span>
      )}
      {badge && <span className="select-card-badge">{badge}</span>}
      {icon && <div className="select-card-icon">{icon}</div>}
      <div className="select-card-title">{title}</div>
      {description && <div className="select-card-description">{description}</div>}
    </div>
  );
}
