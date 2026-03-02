import { useState } from "react";

interface Props {
  label: string;
  initialValue: string;
  onConfirm: (value: string) => void;
  onCancel: () => void;
}

export default function InputDialog({ label, initialValue, onConfirm, onCancel }: Props) {
  const [value, setValue] = useState(initialValue);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onConfirm(value);
  }

  return (
    <div className="dialog-overlay" onClick={onCancel}>
      <form className="dialog-box" onSubmit={handleSubmit} onClick={(e) => e.stopPropagation()}>
        <label className="dialog-label">{label}</label>
        <input
          className="dialog-input"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <div className="dialog-actions">
          <button type="button" className="dialog-btn dialog-btn--cancel" onClick={onCancel}>Cancel</button>
          <button type="submit" className="dialog-btn dialog-btn--confirm">Save</button>
        </div>
      </form>
    </div>
  );
}
