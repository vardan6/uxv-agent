// O13 (minimal): typed contract for the one crossing point where `frontend/`
// loads this legacy vanilla-JS map bundle across the static/React boundary
// (see MapWidgetPanel.tsx). Kept self-contained (no import from frontend/) so
// this stays a one-way contract, not a coupling between the two apps — see
// docs/reviews/2026-07-31-architecture-review.md (candidate F2 / O13).

type LeafletMouseEvent = { latlng: { lat: number; lng: number } };
type LeafletMapHandle = {
  on(event: string, handler: (e: LeafletMouseEvent) => void): void;
  off(event: string, handler: (e: LeafletMouseEvent) => void): void;
};

type ReplayPathPoint = {
  position: { x: number; y: number; z: number } | null;
  gps: { lat: number; lon: number } | null;
};

export type LegacyMapWidget = {
  mount(): void;
  destroy(): void;
  invalidateSize(): void;
  setSessionId(sessionId: string): void;
  setReplayPath(
    points: readonly ReplayPathPoint[],
    georefOrigin?: { lat: number; lon: number } | null,
  ): void;
  setReplayTracks(
    tracks: readonly {
      points: readonly ReplayPathPoint[];
      color?: string;
      visible?: boolean;
      georefOrigin?: { lat: number; lon: number } | null;
    }[],
  ): void;
  clearReplayPath(): void;
  setReplayFrame(index: number, points: readonly ReplayPathPoint[]): void;
  clearReplayFrame(): void;
  setReplayTrackVisible(visible: boolean): void;
  setLiveRoverVisible(visible: boolean): void;
  getLeafletMap(): LeafletMapHandle | null;
};

export const MapWidget: new (
  container: HTMLElement,
  opts?: { sessionId?: string },
) => LegacyMapWidget;

export function enforceVisibilityCap(
  visibleIds: readonly string[],
  max?: number,
  alwaysOn?: readonly string[],
): string[];

export function assignPaletteColor(
  missions: readonly unknown[],
  overrides?: Record<string, string>,
): Record<string, string>;
