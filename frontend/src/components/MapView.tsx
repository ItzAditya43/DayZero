import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
// MapLibre builds its worker URL at runtime, so Vite's static analysis never
// sees it and never emits the file -- the map then fails silently with a
// blank canvas. Bundling the worker explicitly and handing MapLibre the
// resulting URL is the supported fix.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

maplibregl.setWorkerUrl(workerUrl);

// MapLibre with a keyless raster basemap. Deliberately not Mapbox: a token
// that can rate-limit or expire is the last thing you want during judging.
const STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
      maxzoom: 19,
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#05070a" } },
    {
      id: "osm",
      type: "raster",
      source: "osm",
      // Desaturated and darkened so the data layer reads as the subject.
      paint: {
        "raster-opacity": 0.5,
        "raster-saturation": -1,
        "raster-contrast": 0.1,
        "raster-brightness-min": 0.0,
        "raster-brightness-max": 0.32,
      },
    },
  ],
};

type Props = {
  buildings: GeoJSON.FeatureCollection | null;
  selected: number[];
  center: [number, number] | null;
  bbox: number[] | null;
  onPick?: (lat: number, lon: number) => void;
};

export default function MapView({ buildings, selected, center, bbox, onPick }: Props) {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  // Footprints can arrive before the style finishes loading. Park them here
  // rather than waiting on a map event -- an earlier version waited for
  // "idle", which never fires if the basemap tiles are slow or blocked, and
  // the buildings silently never drew.
  const pending = useRef<GeoJSON.FeatureCollection | null>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

  useEffect(() => {
    if (!holder.current || map.current) return;
    const m = new maplibregl.Map({
      container: holder.current,
      style: STYLE,
      center: center ?? [77.5946, 12.9716],
      zoom: 14.2,
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    m.on("load", () => {
      m.addSource("buildings", { type: "geojson", data: pending.current ?? emptyFC() });
      m.addLayer({
        id: "buildings-fill",
        type: "fill",
        source: "buildings",
        paint: {
          "fill-color": [
            "case",
            ["==", ["get", "selected"], 1], "#2dd4bf",
            "#4d7ba8",
          ],
          "fill-opacity": ["case", ["==", ["get", "selected"], 1], 0.9, 0.55],
        },
      });
      m.addLayer({
        id: "buildings-line",
        type: "line",
        source: "buildings",
        paint: {
          "line-color": ["case", ["==", ["get", "selected"], 1], "#5eead4", "#4a6a8f"],
          "line-width": ["case", ["==", ["get", "selected"], 1], 1.4, 0.35],
          "line-opacity": 0.9,
        },
      });
      ready.current = true;
      pending.current = null;
    });

    // MapLibre swallows style and source failures unless you listen for them.
    m.on("error", (e) => console.error("maplibre:", e.error?.message ?? e));

    m.on("click", (e: maplibregl.MapMouseEvent) =>
      pickRef.current?.(e.lngLat.lat, e.lngLat.lng),
    );
    m.getCanvas().style.cursor = "crosshair";
    map.current = m;

    // The map mounts inside a CSS grid cell whose height is only known after
    // layout. Without this the canvas keeps whatever size it had at mount and
    // the map renders into a small corner of its container.
    const ro = new ResizeObserver(() => m.resize());
    ro.observe(holder.current);

    return () => {
      ro.disconnect();
      m.remove();
      map.current = null;
      ready.current = false;
    };
  }, []);

  // Push footprints + selection state into the source.
  useEffect(() => {
    const m = map.current;
    if (!m || !buildings) return;
    const set = new Set(selected);
    const data: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: buildings.features.map((f: GeoJSON.Feature) => ({
        ...f,
        properties: {
          ...f.properties,
          selected: set.has(Number(f.properties?.id)) ? 1 : 0,
        },
      })),
    };
    if (ready.current) {
      const src = m.getSource("buildings") as maplibregl.GeoJSONSource | undefined;
      src?.setData(data);
    } else {
      pending.current = data;
    }
  }, [buildings, selected]);

  // Frame the study area whenever it changes.
  useEffect(() => {
    const m = map.current;
    if (!m || !bbox) return;
    const [s, w, n, e] = bbox;
    const fit = () =>
      m.fitBounds(
        [
          [w, s],
          [e, n],
        ],
        { padding: 40, duration: 900 },
      );
    if (ready.current) fit();
    else m.once("load", fit);
  }, [bbox]);

  // Sized explicitly rather than with `absolute inset-0`: MapLibre's own
  // stylesheet sets `.maplibregl-map { position: relative }` on this element
  // once the map mounts, which overrides the absolute positioning and
  // collapses the container to zero height.
  return <div ref={holder} className="h-full w-full" />;
}

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}
