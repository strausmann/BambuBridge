import { useEffect } from "react";

/** Forms with changes nobody has saved yet; a pending update does not reload over them. */
const dirty = new Set<symbol>();

/** While `isDirty`, the page counts as holding unsaved input (see src/app/updates.ts). */
export function useDirtyGuard(isDirty: boolean): void {
  useEffect(() => {
    if (!isDirty) return;
    const token = Symbol("dirty form");
    dirty.add(token);
    return () => void dirty.delete(token);
  }, [isDirty]);
}

export function hasDirtyForms(): boolean {
  return dirty.size > 0;
}
