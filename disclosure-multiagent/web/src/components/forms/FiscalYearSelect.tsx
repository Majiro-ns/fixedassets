'use client';

import { Select } from '@/components/ui/select';

interface Props {
  value: number;
  onChange: (year: number) => void;
}

const YEARS = [2026, 2025, 2024, 2023, 2022, 2021];

export function FiscalYearSelect({ value, onChange }: Props) {
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium">事業年度</label>
      <Select value={String(value)} onChange={(e) => onChange(Number(e.target.value))}>
        {YEARS.map((y) => (
          <option key={y} value={y}>
            {y}年度
          </option>
        ))}
      </Select>
    </div>
  );
}
