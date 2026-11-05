import { useState, type DragEvent } from 'react';

/** Moves the item at `from` into gap `to` (0..length, gaps of the original list). */
export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  const next = [...items];
  const [item] = next.splice(from, 1);
  next.splice(from < to ? to - 1 : to, 0, item);
  return next;
}

/**
 * Native HTML5 drag-and-drop for a vertical list. `onDrop(from, to)` gets the
 * dragged index and the gap it was dropped into (0..length).
 */
export function useDragReorder(onDrop: (from: number, to: number) => void, enabled = true) {
  const [dragging, setDragging] = useState<number | null>(null);
  const [gap, setGap] = useState<number | null>(null);

  const reset = () => {
    setDragging(null);
    setGap(null);
  };

  const rowProps = (index: number) =>
    enabled
      ? {
          draggable: true,
          onDragStart: (event: DragEvent) => {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', String(index));
            setDragging(index);
          },
          onDragOver: (event: DragEvent<HTMLElement>) => {
            event.preventDefault();
            const rect = event.currentTarget.getBoundingClientRect();
            setGap(event.clientY < rect.top + rect.height / 2 ? index : index + 1);
          },
          onDrop: (event: DragEvent) => {
            event.preventDefault();
            if (dragging !== null && gap !== null && gap !== dragging && gap !== dragging + 1) onDrop(dragging, gap);
            reset();
          },
          onDragEnd: reset,
        }
      : {};

  return { dragging, gap, rowProps };
}
