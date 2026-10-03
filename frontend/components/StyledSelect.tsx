"use client";

import { useEffect, useRef, useState } from "react";

export interface SelectOption {
  value: string;
  label: string;
}

/**
 * Styled dropdown replacing native <select> — glass popover, hover states,
 * checkmark on the selected item, click-outside and Escape to close.
 */
export function StyledSelect({
  value,
  options,
  onChange,
  placeholder = "— select —",
  ariaLabel,
}: {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="styled-select" ref={rootRef}>
      <button
        type="button"
        className={`styled-select-trigger ${open ? "open" : ""}`}
        aria-label={ariaLabel}
        onClick={() => setOpen(!open)}
      >
        <span className={selected ? "" : "placeholder"}>
          {selected ? selected.label : placeholder}
        </span>
        <span className={`chev ${open ? "up" : ""}`}>▾</span>
      </button>
      {open && (
        <div className="styled-select-pop" role="listbox">
          {options.length === 0 && <div className="styled-select-empty">No options</div>}
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              role="option"
              aria-selected={o.value === value}
              className={`styled-select-item ${o.value === value ? "selected" : ""}`}
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
            >
              <span>{o.label}</span>
              {o.value === value && <span className="check">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
