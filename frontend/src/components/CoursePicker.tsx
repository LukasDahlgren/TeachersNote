import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { Course } from "../types";

interface CoursePickerProps {
  courses: Course[];
  value: string | null;
  onChange: (courseCode: string | null) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function CoursePicker({
  courses,
  value,
  onChange,
  disabled = false,
  placeholder = "Select course (optional)",
}: CoursePickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const isOpen = open && !disabled;

  const selected = courses.find((c) => c.code === value) ?? null;

  const filtered = courses.filter((c) => {
    const q = search.trim().toLowerCase();
    return !q || c.code.toLowerCase().includes(q) || c.name.toLowerCase().includes(q);
  });

  useEffect(() => {
    if (!isOpen) return;
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (!rootRef.current?.contains(target) && !popoverRef.current?.contains(target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) { setSearch(""); return; }
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPopoverStyle({
        position: "fixed",
        top: rect.bottom + 4,
        left: rect.left,
        width: rect.width,
        zIndex: 9999,
      });
    }
    const t = window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [isOpen]);

  function select(code: string | null) {
    onChange(code);
    setSearch("");
    setOpen(false);
  }

  return (
    <div className="course-picker" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`course-picker-trigger${isOpen ? " course-picker-trigger--open" : ""}`}
        disabled={disabled}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className={`course-picker-trigger-text${!selected ? " course-picker-trigger-text--placeholder" : ""}`}>
          {selected
            ? `${selected.name} (${selected.display_code ?? selected.code})`
            : placeholder}
        </span>
        <span className="course-picker-trigger-chevron">▾</span>
      </button>

      {isOpen && createPortal(
        <div ref={popoverRef} className="course-picker-popover" style={popoverStyle}>
          <div className="course-picker-search">
            <input
              ref={searchRef}
              type="search"
              className="course-picker-search-input"
              placeholder="Search courses…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {value && (
            <button
              type="button"
              className="course-picker-course-btn"
              onClick={() => select(null)}
            >
              <span className="course-picker-course-name" style={{ color: "#6b7280", fontStyle: "italic" }}>
                No course selected
              </span>
            </button>
          )}

          {filtered.length === 0 ? (
            <p className="course-picker-empty">No courses found.</p>
          ) : (
            <div className="course-picker-course-list" style={{ marginLeft: 0, borderLeft: "none", paddingLeft: "0.12rem" }}>
              {filtered.map((course) => (
                <button
                  key={course.id}
                  type="button"
                  className={`course-picker-course-btn${course.code === value ? " course-picker-course-btn--active" : ""}`}
                  onClick={() => select(course.code)}
                >
                  <span className="course-picker-course-code">{course.display_code ?? course.code}</span>
                  <span className="course-picker-course-name">{course.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>,
        document.body
      )}
    </div>
  );
}
