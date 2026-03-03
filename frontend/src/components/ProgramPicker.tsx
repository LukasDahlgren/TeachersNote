import { useEffect, useMemo, useRef, useState } from "react";
import type { Program } from "../types";

interface ProgramPickerProps {
  id?: string;
  value: number | null;
  programs: Program[];
  onChange: (programId: number | null) => void;
  disabled?: boolean;
  showAllOption?: boolean;
  showAllLabel?: string;
  placeholder?: string;
  className?: string;
}

export default function ProgramPicker({
  id,
  value,
  programs,
  onChange,
  disabled = false,
  showAllOption = false,
  showAllLabel = "Show all",
  placeholder = "Select a program",
  className,
}: ProgramPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const isOpen = open && !disabled;

  const selectedProgram = useMemo(
    () => programs.find((program) => program.id === value) ?? null,
    [programs, value],
  );

  const filteredPrograms = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    if (!normalized) return programs;
    return programs.filter((program) =>
      `${program.name} ${program.code}`.toLowerCase().includes(normalized),
    );
  }, [programs, search]);

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      setSearch("");
      return;
    }
    const timer = window.setTimeout(() => {
      searchInputRef.current?.focus();
    }, 0);
    return () => {
      window.clearTimeout(timer);
    };
  }, [isOpen]);

  function selectProgram(programId: number | null) {
    onChange(programId);
    setSearch("");
    setOpen(false);
  }

  const rootClassName = `program-picker${className ? ` ${className}` : ""}`;

  return (
    <div className={rootClassName} ref={rootRef}>
      <button
        id={id}
        type="button"
        className={`program-picker-trigger${isOpen ? " program-picker-trigger--open" : ""}`}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={id ? `${id}-menu` : undefined}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className={`program-picker-trigger-text${(selectedProgram || value === null) ? "" : " program-picker-trigger-text--placeholder"}`}>
          {selectedProgram
            ? `${selectedProgram.name} (${selectedProgram.code})${selectedProgram.is_active ? "" : " · Inactive"}`
            : (showAllOption && value === null ? showAllLabel : placeholder)}
        </span>
        <span className="program-picker-trigger-chevron">▾</span>
      </button>

      {isOpen && (
        <div
          id={id ? `${id}-menu` : undefined}
          className="program-picker-popover"
          role="listbox"
          aria-label="Program picker"
        >
          <div className="program-picker-search">
            <input
              ref={searchInputRef}
              type="search"
              className="program-picker-search-input"
              placeholder="Search programs..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>

          {showAllOption && (
            <button
              type="button"
              className={`program-picker-option${value === null ? " program-picker-option--active" : ""}`}
              onClick={() => selectProgram(null)}
            >
              <span className="program-picker-option-name">{showAllLabel}</span>
            </button>
          )}

          {filteredPrograms.map((program) => (
            <button
              key={program.id}
              type="button"
              className={`program-picker-option${program.id === value ? " program-picker-option--active" : ""}`}
              onClick={() => selectProgram(program.id)}
            >
              <span className="program-picker-option-name">{program.name}</span>
              <span className="program-picker-option-meta">
                {program.code}{program.is_active ? "" : " · Inactive"}
              </span>
            </button>
          ))}

          {filteredPrograms.length === 0 && (
            <p className="program-picker-empty">
              {programs.length === 0 ? "No programs available." : "No programs match your search."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
