// useInert: sets the HTML `inert` attribute through a ref. React 18's JSX
// types have no `inert` prop (and React 18 would not pass a boolean through
// for it), so the loading overlay toggles the attribute on the DOM element.
// An inert subtree stays mounted (its tracked loads keep running) but takes no
// focus, clicks or keyboard input, which disables every send action in it.
import { useEffect, useRef } from 'react';

export function useInert<T extends HTMLElement = HTMLDivElement>(on: boolean) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.toggleAttribute('inert', on);
    return () => el.removeAttribute('inert');
  }, [on]);
  return ref;
}
