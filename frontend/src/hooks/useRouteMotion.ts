import { useCallback, useEffect, useRef, useState } from "react";
import type { Location } from "react-router-dom";

export type RouteMotionPhase = "idle" | "exit" | "enter";

interface UseRouteMotionOptions {
  exitMs?: number;
  enterMs?: number;
  transitionKey?: string;
}

function canUseMatchMedia(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function";
}

export function useRouteMotion(
  location: Location,
  options: UseRouteMotionOptions = {},
): { displayLocation: Location; phase: RouteMotionPhase; reducedMotion: boolean } {
  const exitMs = options.exitMs ?? 120;
  const enterMs = options.enterMs ?? 180;
  const transitionKey = options.transitionKey ?? location.pathname;

  const [displayLocation, setDisplayLocation] = useState(location);
  const [phase, setPhase] = useState<RouteMotionPhase>("idle");
  const [reducedMotion, setReducedMotion] = useState(() => (
    canUseMatchMedia()
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false
  ));

  const previousTransitionKeyRef = useRef(transitionKey);
  const frameRef = useRef<number | null>(null);
  const exitTimerRef = useRef<number | null>(null);
  const enterTimerRef = useRef<number | null>(null);

  const clearPendingAnimations = useCallback(() => {
    if (exitTimerRef.current !== null) {
      window.clearTimeout(exitTimerRef.current);
      exitTimerRef.current = null;
    }
    if (enterTimerRef.current !== null) {
      window.clearTimeout(enterTimerRef.current);
      enterTimerRef.current = null;
    }
    if (frameRef.current !== null) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!canUseMatchMedia()) return;

    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateFromMediaQuery = () => {
      setReducedMotion(mediaQuery.matches);
    };

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", updateFromMediaQuery);
    } else {
      mediaQuery.addListener(updateFromMediaQuery);
    }

    return () => {
      if (typeof mediaQuery.removeEventListener === "function") {
        mediaQuery.removeEventListener("change", updateFromMediaQuery);
      } else {
        mediaQuery.removeListener(updateFromMediaQuery);
      }
    };
  }, []);

  useEffect(() => {
    return () => {
      clearPendingAnimations();
    };
  }, [clearPendingAnimations]);

  useEffect(() => {
    if (transitionKey === previousTransitionKeyRef.current) {
      return;
    }

    previousTransitionKeyRef.current = transitionKey;
    clearPendingAnimations();

    if (reducedMotion) {
      frameRef.current = window.requestAnimationFrame(() => {
        setDisplayLocation(location);
        setPhase("idle");
      });
      return;
    }

    frameRef.current = window.requestAnimationFrame(() => {
      setPhase("exit");
    });
    exitTimerRef.current = window.setTimeout(() => {
      setDisplayLocation(location);
      setPhase("enter");

      frameRef.current = window.requestAnimationFrame(() => {
        enterTimerRef.current = window.setTimeout(() => {
          setPhase("idle");
        }, enterMs);
      });
    }, exitMs);
  }, [clearPendingAnimations, enterMs, exitMs, location, reducedMotion, transitionKey]);

  return {
    displayLocation,
    phase,
    reducedMotion,
  };
}
