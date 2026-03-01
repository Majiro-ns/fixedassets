import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { NenchoCsvRecord } from '@/types/nencho_csv';

/** localStorage キー（他プロジェクトと衝突しないよう nencho 固有に設定） */
const STORAGE_KEY = 'nencho-training-data';

interface NenchoTrainingState {
  records: NenchoCsvRecord[];
  addRecords: (records: NenchoCsvRecord[]) => void;
  clearRecords: () => void;
  deleteRecord: (index: number) => void;
}

export const useNenchoTrainingStore = create<NenchoTrainingState>()(
  persist(
    (set) => ({
      records: [],
      addRecords: (records) =>
        set((state) => ({ records: [...state.records, ...records] })),
      clearRecords: () => set({ records: [] }),
      deleteRecord: (index) =>
        set((state) => ({
          records: state.records.filter((_, i) => i !== index),
        })),
    }),
    { name: STORAGE_KEY },
  ),
);
