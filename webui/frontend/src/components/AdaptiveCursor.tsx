import { useEffect, useRef } from 'react';
import { useApp } from '../store/AppContext';

/**
 * Pure zero-DOM-mutation Apple iPadOS adaptive pointer overlay.
 * Never overrides target element transform/transition or blocks native clicks/text carets.
 */
export function AdaptiveCursor() {
  const { cursorEnabled, theme } = useApp();
  const pillRef = useRef<HTMLDivElement | null>(null);

  // Subtle edge gleam tracking on .glass-gleam containers
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      const gleamEl = target?.closest('.glass-gleam') as HTMLElement | null;
      if (gleamEl) {
        const rect = gleamEl.getBoundingClientRect();
        gleamEl.style.setProperty('--mx', `${e.clientX - rect.left}px`);
        gleamEl.style.setProperty('--my', `${e.clientY - rect.top}px`);
      }
    };
    window.addEventListener('mousemove', onMove, { passive: true });
    return () => window.removeEventListener('mousemove', onMove);
  }, []);

  useEffect(() => {
    const isCoarse = window.matchMedia('(pointer: coarse)').matches;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!cursorEnabled || isCoarse || reduceMotion) return;

    const pill = pillRef.current;
    if (!pill) return;

    let visible = false;
    let pressed = false;
    let hoverBlock: HTMLElement | null = null;
    let mouseX = -200;
    let mouseY = -200;

    const curr = { x: -200, y: -200, w: 8, h: 8, r: 4 };
    let raf = 0;

    const findInteractive = (target: EventTarget | null): HTMLElement | null => {
      if (!(target instanceof Element)) return null;
      if (target.closest('input, textarea, select, [contenteditable="true"], svg.touch-none')) {
        return null;
      }
      const el = target.closest(
        'button:not(:disabled), a[href], [role="tab"], [data-cursor="block"]',
      );
      return el instanceof HTMLElement ? el : null;
    };

    const isNativeInput = (target: EventTarget | null) =>
      target instanceof Element &&
      Boolean(target.closest('input, textarea, select, [contenteditable="true"], svg.touch-none'));

    const onPointerMove = (e: PointerEvent) => {
      mouseX = e.clientX;
      mouseY = e.clientY;
      if (!visible) {
        visible = true;
        curr.x = mouseX;
        curr.y = mouseY;
      }
      hoverBlock = findInteractive(e.target);
      if (isNativeInput(e.target)) {
        pill.style.opacity = '0';
      } else {
        pill.style.opacity = '1';
      }
    };

    const onPointerDown = () => {
      pressed = true;
    };
    const onPointerUp = () => {
      pressed = false;
    };
    const onLeave = () => {
      visible = false;
      hoverBlock = null;
      pill.style.opacity = '0';
    };

    const tick = () => {
      let targetX = mouseX;
      let targetY = mouseY;
      let targetW = 8;
      let targetH = 8;
      let targetR = 4;

      if (hoverBlock && hoverBlock.isConnected) {
        const rect = hoverBlock.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && rect.width < 420 && rect.height < 140) {
          const isTab =
            hoverBlock.getAttribute('role') === 'tab' ||
            Boolean(hoverBlock.closest('nav')) ||
            hoverBlock.hasAttribute('data-cursor-wide');
          const isCompactIcon = rect.width <= 38 && rect.height <= 38;
          const padX = isTab ? 8 : isCompactIcon ? 4 : 6;
          const padY = isTab ? 4 : isCompactIcon ? 4 : 4;
          targetW = rect.width + padX * 2;
          targetH = rect.height + padY * 2;
          // Subtle parallax nudge toward cursor inside button
          const dx = Math.max(-1, Math.min(1, (mouseX - (rect.left + rect.width / 2)) / (rect.width / 2)));
          const dy = Math.max(-1, Math.min(1, (mouseY - (rect.top + rect.height / 2)) / (rect.height / 2)));
          targetX = rect.left + rect.width / 2 + dx * 2.5;
          targetY = rect.top + rect.height / 2 + dy * 2.5;
          const computedRadius = parseFloat(window.getComputedStyle(hoverBlock).borderRadius || '8');
          targetR = Number.isFinite(computedRadius) ? Math.min(14, Math.max(8, computedRadius + 3)) : 10;
        }
      }

      const speed = 0.28;
      curr.x += (targetX - curr.x) * speed;
      curr.y += (targetY - curr.y) * speed;
      curr.w += (targetW - curr.w) * speed;
      curr.h += (targetH - curr.h) * speed;
      curr.r += (targetR - curr.r) * speed;

      const scale = pressed ? (hoverBlock ? 0.97 : 0.82) : 1;
      pill.style.width = `${curr.w.toFixed(1)}px`;
      pill.style.height = `${curr.h.toFixed(1)}px`;
      pill.style.borderRadius = `${curr.r.toFixed(1)}px`;
      pill.style.transform = `translate3d(${(curr.x - curr.w / 2).toFixed(1)}px, ${(curr.y - curr.h / 2).toFixed(1)}px, 0) scale(${scale})`;

      raf = requestAnimationFrame(tick);
    };

    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerdown', onPointerDown, { passive: true });
    window.addEventListener('pointerup', onPointerUp, { passive: true });
    document.addEventListener('mouseleave', onLeave);
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointerup', onPointerUp);
      document.removeEventListener('mouseleave', onLeave);
    };
  }, [cursorEnabled]);

  if (!cursorEnabled) return null;

  const isDark = theme === 'dark';

  return (
    <div
      ref={pillRef}
      aria-hidden="true"
      className="pointer-events-none fixed left-0 top-0 z-[9999] opacity-0 transition-opacity duration-150"
      style={{
        backgroundColor: isDark ? 'rgba(107, 163, 224, 0.14)' : 'rgba(37, 92, 140, 0.09)',
        border: isDark
          ? '1px solid rgba(107, 163, 224, 0.28)'
          : '1px solid rgba(37, 92, 140, 0.18)',
      }}
    />
  );
}
