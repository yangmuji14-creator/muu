import { useEffect, useRef } from 'react';
import { ThemeMode } from '../store/AppContext';

const PALETTE_LIGHT = [
  '#3B82F6',
  '#6366F1',
  '#0EA5E9',
  '#14B8A6',
  '#8B5CF6',
  '#EC4899',
  '#F59E0B',
];

const PALETTE_DARK = [
  '#60A5FA',
  '#818CF8',
  '#38BDF8',
  '#2DD4BF',
  '#A78BFA',
  '#F472B6',
  '#FBBF24',
];

interface AmbientParticle {
  x: number;
  y: number;
  baseX: number;
  baseY: number;
  vx: number;
  vy: number;
  radius: number;
  isCapsule: boolean;
  angle: number;
  spin: number;
  phase: number;
  driftSpeed: number;
  colorIdx: number;
  baseAlpha: number;
}

interface TrailPoint {
  x: number;
  y: number;
  ts: number;
  colorIdx: number;
}

interface TrailSpark {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  born: number;
  life: number;
  colorIdx: number;
}

function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  const n = parseInt(clean, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
}

/**
 * Antigravity-inspired free-floating colorful micro-particles + cursor repulsion + silky multi-tone trail.
 * Only mounted on the empty welcome stage so conversation reading stays ultra-clean.
 */
export function InteractiveTileCanvas({
  theme,
  enabled,
}: {
  theme: ThemeMode;
  enabled: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;
    let width = 0;
    let height = 0;
    let t = 0;

    const particles: AmbientParticle[] = [];
    const trailPoints: TrailPoint[] = [];
    const sparks: TrailSpark[] = [];

    const mouse = { x: -9999, y: -9999, active: false, lastX: -9999, lastY: -9999 };
    let hueTick = 0;

    const seedParticles = () => {
      particles.length = 0;
      if (width <= 0 || height <= 0) return;
      const count = Math.min(130, Math.max(90, Math.round((width * height) / 11500)));
      for (let i = 0; i < count; i++) {
        const px = Math.random() * width;
        const py = Math.random() * height;
        particles.push({
          x: px,
          y: py,
          baseX: px,
          baseY: py,
          vx: 0,
          vy: 0,
          radius: 1.8 + Math.random() * 2.2,
          isCapsule: Math.random() < 0.35,
          angle: Math.random() * Math.PI * 2,
          spin: (Math.random() - 0.5) * 0.015,
          phase: Math.random() * Math.PI * 2,
          driftSpeed: 0.14 + Math.random() * 0.2,
          colorIdx: i % PALETTE_LIGHT.length,
          baseAlpha: 0.38 + Math.random() * 0.38,
        });
      }
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seedParticles();
    };

    const onMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      mouse.x = x;
      mouse.y = y;
      mouse.active = x >= 0 && x <= width && y >= 0 && y <= height;

      if (!reduceMotion && mouse.active) {
        const now = performance.now();
        const distFromLast =
          mouse.lastX < -5000 ? 99 : Math.hypot(x - mouse.lastX, y - mouse.lastY);

        if (distFromLast >= 4) {
          const dx = mouse.lastX < -5000 ? 0 : x - mouse.lastX;
          const dy = mouse.lastY < -5000 ? 0 : y - mouse.lastY;
          hueTick = (hueTick + 1) % PALETTE_LIGHT.length;

          trailPoints.push({ x, y, ts: now, colorIdx: hueTick });
          if (trailPoints.length > 16) trailPoints.shift();

          const spawnCount = distFromLast > 18 ? 2 : 1;
          for (let s = 0; s < spawnCount; s++) {
            const len = Math.max(1, Math.hypot(dx, dy));
            const spreadAngle = Math.atan2(-dy, -dx) + (Math.random() - 0.5) * 1.1;
            const speed = Math.min(2.2, 0.35 + len * 0.045) * (0.6 + Math.random() * 0.6);
            sparks.push({
              x: x + (Math.random() - 0.5) * 6,
              y: y + (Math.random() - 0.5) * 6,
              vx: Math.cos(spreadAngle) * speed,
              vy: Math.sin(spreadAngle) * speed,
              radius: 1.7 + Math.random() * 2.1,
              born: now,
              life: 480 + Math.random() * 170,
              colorIdx: (hueTick + s) % PALETTE_LIGHT.length,
            });
          }
          if (sparks.length > 90) sparks.splice(0, sparks.length - 90);

          mouse.lastX = x;
          mouse.lastY = y;
        }
      }
    };

    const onLeave = () => {
      mouse.active = false;
      mouse.x = -9999;
      mouse.y = -9999;
      mouse.lastX = -9999;
      mouse.lastY = -9999;
    };

    const drawFrame = () => {
      ctx.clearRect(0, 0, width, height);
      const now = performance.now();
      const isDark = theme === 'dark';
      const palette = isDark ? PALETTE_DARK : PALETTE_LIGHT;

      if (!reduceMotion) t += 0.016;

      const cx = width * 0.5;
      const cy = height * 0.46;
      const clearRadius = Math.min(width, height) * 0.42;
      const repulseRadius = 155;

      // Layer 1: Ambient colorful antigravity particles
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];

        if (!reduceMotion) {
          p.baseY -= p.driftSpeed;
          p.baseX += Math.sin(t + p.phase) * 0.18;
          p.angle += p.spin;

          if (p.baseY < -14) {
            p.baseY = height + 14;
            p.baseX = Math.random() * width;
            p.x = p.baseX;
            p.y = p.baseY;
          }
          if (p.baseX < -14) p.baseX = width + 14;
          if (p.baseX > width + 14) p.baseX = -14;

          if (mouse.active) {
            const dx = p.x - mouse.x;
            const dy = p.y - mouse.y;
            const dist = Math.hypot(dx, dy);
            if (dist > 0.1 && dist < repulseRadius) {
              const force = Math.pow(1 - dist / repulseRadius, 1.5) * 2.1;
              p.vx += (dx / dist) * force;
              p.vy += (dy / dist) * force;
            }
          }

          // Spring pull back toward ambient drift anchor
          p.vx += (p.baseX - p.x) * 0.035;
          p.vy += (p.baseY - p.y) * 0.035;
          p.vx *= 0.86;
          p.vy *= 0.86;
          p.x += p.vx;
          p.y += p.vy;
        }

        const distCenter = Math.hypot(p.x - cx, p.y - cy);
        const centerFade = Math.min(1, 0.28 + (distCenter / Math.max(120, clearRadius)) * 0.65);
        const breath = reduceMotion ? 1 : 0.88 + Math.sin(t * 1.4 + p.phase) * 0.12;
        const alpha = Math.min(0.78, p.baseAlpha * centerFade * breath);

        const hex = palette[p.colorIdx % palette.length];
        ctx.fillStyle = hexToRgba(hex, alpha);

        if (p.isCapsule) {
          ctx.save();
          ctx.translate(p.x, p.y);
          ctx.rotate(p.angle);
          const w = p.radius * 3.1;
          const h = p.radius * 1.15;
          ctx.beginPath();
          ctx.roundRect(-w / 2, -h / 2, w, h, h / 2);
          ctx.fill();
          ctx.restore();
        } else {
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // Layer 2A: Silky multi-tone cursor ribbon trail
      if (!reduceMotion) {
        while (trailPoints.length > 0 && now - trailPoints[0].ts > 460) {
          trailPoints.shift();
        }
        if (trailPoints.length > 1) {
          ctx.save();
          ctx.lineCap = 'round';
          ctx.lineJoin = 'round';
          const maxAlpha = isDark ? 0.38 : 0.28;
          for (let i = 1; i < trailPoints.length; i++) {
            const prev = trailPoints[i - 1];
            const curr = trailPoints[i];
            const ratio = i / (trailPoints.length - 1);
            const ageFade = Math.max(0, 1 - (now - curr.ts) / 460);
            const alpha = maxAlpha * ratio * ageFade;
            if (alpha <= 0.01) continue;

            const c1 = palette[prev.colorIdx % palette.length];
            const c2 = palette[curr.colorIdx % palette.length];
            const grad = ctx.createLinearGradient(prev.x, prev.y, curr.x, curr.y);
            grad.addColorStop(0, hexToRgba(c1, alpha * 0.8));
            grad.addColorStop(1, hexToRgba(c2, alpha));

            ctx.strokeStyle = grad;
            ctx.lineWidth = 0.6 + ratio * 2.6;
            ctx.beginPath();
            ctx.moveTo(prev.x, prev.y);
            ctx.lineTo(curr.x, curr.y);
            ctx.stroke();
          }
          ctx.restore();
        }

        // Layer 2B: Multi-tone trailing sparks
        for (let i = sparks.length - 1; i >= 0; i--) {
          const sp = sparks[i];
          const age = now - sp.born;
          if (age >= sp.life) {
            sparks.splice(i, 1);
            continue;
          }
          const progress = age / sp.life;
          sp.x += sp.vx;
          sp.y += sp.vy;
          sp.vx *= 0.94;
          sp.vy *= 0.94;

          const r = sp.radius * (1 - progress * 0.72);
          const alpha = (isDark ? 0.78 : 0.66) * Math.pow(1 - progress, 1.4);
          if (r <= 0.25 || alpha <= 0.01) continue;

          ctx.fillStyle = hexToRgba(palette[sp.colorIdx % palette.length], alpha);
          ctx.beginPath();
          ctx.arc(sp.x, sp.y, r, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      if (!reduceMotion) {
        raf = requestAnimationFrame(drawFrame);
      }
    };

    resize();
    drawFrame();

    const ro = new ResizeObserver(() => {
      resize();
      if (reduceMotion) drawFrame();
    });
    ro.observe(canvas);
    window.addEventListener('mousemove', onMove, { passive: true });
    window.addEventListener('mouseleave', onLeave);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseleave', onLeave);
    };
  }, [theme, enabled]);

  if (!enabled) return null;

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  );
}
