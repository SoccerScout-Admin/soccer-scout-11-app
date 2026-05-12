/**
 * useScrollIntoViewOnOpen
 * -----------------------
 * Auto-scrolls the attached element into view when `open` flips false→true.
 * Built for the iter57 "click a button → form expands → page doesn't move"
 * UX bug. Works on both desktop and mobile (no special mobile branching
 * needed — smooth scrollIntoView is widely supported).
 *
 * Usage:
 *   const scrollRef = useScrollIntoViewOnOpen(showAddForm);
 *   ...
 *   {showAddForm && <form ref={scrollRef}>...</form>}
 *
 * Why a small delay? React renders the form THEN we want to scroll, not
 * before the DOM node exists. 60ms is enough for a paint cycle on slow
 * mobile devices without making the scroll feel disconnected from the click.
 *
 * The block: 'center' puts the form mid-viewport on mobile so the user sees
 * both the form AND a hint of the button they just clicked above it —
 * preserves spatial context.
 */
import { useEffect, useRef } from 'react';

export const useScrollIntoViewOnOpen = (open) => {
  const ref = useRef(null);

  useEffect(() => {
    if (!open || !ref.current) return undefined;
    const t = setTimeout(() => {
      if (!ref.current) return;
      try {
        ref.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
      } catch {
        // Fallback for older browsers that reject the options arg
        ref.current.scrollIntoView();
      }
      // Try to focus the first focusable input so mobile keyboards pop up
      // immediately — saves one tap. Only auto-focus when an input is the
      // intended primary action (form-style usage).
      const firstInput = ref.current.querySelector(
        'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])'
      );
      if (firstInput) {
        try { firstInput.focus({ preventScroll: true }); } catch { /* ignore */ }
      }
    }, 60);
    return () => clearTimeout(t);
  }, [open]);

  return ref;
};

export default useScrollIntoViewOnOpen;
