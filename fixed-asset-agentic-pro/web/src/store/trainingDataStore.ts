import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { TrainingRecord } from '@/types/training_data';

const STORAGE_KEY = 'training-data';

interface TrainingDataState {
  records: TrainingRecord[];
  addRecords: (records: TrainingRecord[]) => void;
  clearRecords: () => void;
  deleteRecord: (index: number) => void;
  updateRecord: (index: number, record: TrainingRecord) => void;
}

export const useTrainingDataStore = create<TrainingDataState>()(
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
      updateRecord: (index, record) =>
        set((state) => ({
          records: state.records.map((r, i) => (i === index ? record : r)),
        })),
    }),
    { name: STORAGE_KEY },
  ),
);
