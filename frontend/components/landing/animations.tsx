"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

export type EaseFn = (t: number) => number;

export const Easing: Record<string, EaseFn> = {
  linear: (t) => t,

  easeInQuad: (t) => t * t,
  easeOutQuad: (t) => t * (2 - t),
  easeInOutQuad: (t) => (t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t),

  easeInCubic: (t) => t * t * t,
  easeOutCubic: (t) => {
    const u = t - 1;
    return u * u * u + 1;
  },
  easeInOutCubic: (t) =>
    t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1,

  easeInQuart: (t) => t * t * t * t,
  easeOutQuart: (t) => {
    const u = t - 1;
    return 1 - u * u * u * u;
  },

  easeInExpo: (t) => (t === 0 ? 0 : Math.pow(2, 10 * (t - 1))),
  easeOutExpo: (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)),

  easeInSine: (t) => 1 - Math.cos((t * Math.PI) / 2),
  easeOutSine: (t) => Math.sin((t * Math.PI) / 2),

  easeOutBack: (t) => {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },
  easeInBack: (t) => {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return c3 * t * t * t - c1 * t * t;
  },

  easeOutElastic: (t) => {
    const c4 = (2 * Math.PI) / 3;
    if (t === 0) return 0;
    if (t === 1) return 1;
    return Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * c4) + 1;
  },
};

export const clamp = (v: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, v));

export function interpolate(
  input: number[],
  output: number[],
  ease: EaseFn | EaseFn[] = Easing.linear,
): (t: number) => number {
  return (t: number) => {
    if (t <= input[0]) return output[0];
    if (t >= input[input.length - 1]) return output[output.length - 1];
    for (let i = 0; i < input.length - 1; i++) {
      if (t >= input[i] && t <= input[i + 1]) {
        const span = input[i + 1] - input[i];
        const local = span === 0 ? 0 : (t - input[i]) / span;
        const easeFn = Array.isArray(ease) ? ease[i] || Easing.linear : ease;
        const eased = easeFn(local);
        return output[i] + (output[i + 1] - output[i]) * eased;
      }
    }
    return output[output.length - 1];
  };
}

export interface AnimateOptions {
  from?: number;
  to?: number;
  start?: number;
  end?: number;
  ease?: EaseFn;
}

export function animate({
  from = 0,
  to = 1,
  start = 0,
  end = 1,
  ease = Easing.easeInOutCubic,
}: AnimateOptions = {}): (t: number) => number {
  return (t: number) => {
    if (t <= start) return from;
    if (t >= end) return to;
    const local = (t - start) / (end - start);
    return from + (to - from) * ease(local);
  };
}

export interface TimelineValue {
  time: number;
  duration: number;
  playing: boolean;
}

export const TimelineContext = createContext<TimelineValue>({
  time: 0,
  duration: 10,
  playing: false,
});

export const useTime = (): number => useContext(TimelineContext).time;
export const useTimeline = (): TimelineValue => useContext(TimelineContext);

export interface SpriteValue {
  localTime: number;
  progress: number;
  duration: number;
  visible: boolean;
}

const SpriteContext = createContext<SpriteValue>({
  localTime: 0,
  progress: 0,
  duration: 0,
  visible: false,
});

export const useSprite = (): SpriteValue => useContext(SpriteContext);

export interface SpriteProps {
  start?: number;
  end?: number;
  keepMounted?: boolean;
  children: ReactNode | ((value: SpriteValue) => ReactNode);
}

export function Sprite({
  start = 0,
  end = Infinity,
  children,
  keepMounted = false,
}: SpriteProps) {
  const { time } = useTimeline();
  const visible = time >= start && time <= end;
  if (!visible && !keepMounted) return null;

  const duration = end - start;
  const localTime = Math.max(0, time - start);
  const progress =
    duration > 0 && isFinite(duration) ? clamp(localTime / duration, 0, 1) : 0;

  const value: SpriteValue = { localTime, progress, duration, visible };

  return (
    <SpriteContext.Provider value={value}>
      {typeof children === "function" ? children(value) : children}
    </SpriteContext.Provider>
  );
}

export interface StageProps {
  width?: number;
  height?: number;
  duration?: number;
  background?: string;
  loop?: boolean;
  autoplay?: boolean;
  children: ReactNode;
}

export function Stage({
  width = 1280,
  height = 720,
  duration = 10,
  background = "#f6f4ef",
  loop = true,
  autoplay = true,
  children,
}: StageProps) {
  const [time, setTime] = useState(0);
  const [scale, setScale] = useState(1);

  const hostRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastTsRef = useRef<number | null>(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const measure = () => {
      const s = el.clientWidth / width;
      setScale(Math.max(0.05, s));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [width]);

  useEffect(() => {
    if (!autoplay) {
      lastTsRef.current = null;
      return;
    }
    const step = (ts: number) => {
      if (lastTsRef.current == null) lastTsRef.current = ts;
      const dt = (ts - lastTsRef.current) / 1000;
      lastTsRef.current = ts;
      setTime((t) => {
        let next = t + dt;
        if (next >= duration) {
          if (loop) next = next % duration;
          else next = duration;
        }
        return next;
      });
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      lastTsRef.current = null;
    };
  }, [autoplay, duration, loop]);

  const ctxValue = useMemo<TimelineValue>(
    () => ({ time, duration, playing: autoplay }),
    [time, duration, autoplay],
  );

  const hostStyle: CSSProperties = {
    position: "absolute",
    inset: 0,
    overflow: "hidden",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  };

  const canvasStyle: CSSProperties = {
    width,
    height,
    background,
    position: "relative",
    transform: `scale(${scale})`,
    transformOrigin: "center center",
    flexShrink: 0,
  };

  return (
    <div ref={hostRef} style={hostStyle}>
      <div style={canvasStyle}>
        <TimelineContext.Provider value={ctxValue}>
          {children}
        </TimelineContext.Provider>
      </div>
    </div>
  );
}
