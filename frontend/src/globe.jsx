import React, { useEffect, useId, useRef, useState } from 'react';
import { geoDistance, geoGraticule10, geoOrthographic, geoPath } from 'd3-geo';
import { feature } from 'topojson-client';
import world from 'world-atlas/land-110m.json';

// Approximate port locations for the synthetic network. Coordinates are longitude, latitude.
const coordinates = {
  P01: [-74.03, 40.67], P02: [-95.27, 29.73], P03: [-81.15, 32.13], P04: [-118.26, 33.74],
  P05: [31.04, -29.88], P06: [18.44, -33.91], P07: [25.63, -33.96], P08: [39.65, -4.06],
  P09: [39.29, -6.83], P10: [0.0, 5.63], P11: [72.84, 18.94], P12: [69.72, 22.74],
  P13: [80.30, 13.09], P14: [76.26, 9.96], P15: [83.29, 17.69], P16: [103.82, 1.27],
  P17: [79.84, 6.95], P18: [55.05, 25.01], P19: [4.10, 51.96], P20: [57.49, -20.15],
};
const home = { longitude: -3, latitude: -1, zoom: 1 };
const sphere = { type: 'Sphere' };
const land = feature(world, world.objects.land);
const grid = geoGraticule10();
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

export function ShippingGlobe({ ports, routes, portId, selectPort, demo, affectedPorts }) {
  const [view, setView] = useState(home);
  const [size, setSize] = useState([640, 440]);
  const surface = useRef(null);
  const pointers = useRef(new Map());
  const ocean = useId();
  const direction = ocean + '-direction';
  const [width, height] = size;
  const radius = Math.max(1, Math.min(width, height) / 2 - 18);
  const projection = geoOrthographic().rotate([-view.longitude, -view.latitude])
    .translate([width / 2, height / 2]).scale(radius * view.zoom).clipAngle(90).precision(.7);
  const path = geoPath(projection);
  const center = [view.longitude, view.latitude];
  const visible = (position) => geoDistance(center, position) < Math.PI / 2;
  const adjustZoom = (factor) => setView((current) => ({
    ...current, zoom: clamp(current.zoom * factor, .75, 4),
  }));
  const rotate = (x, y) => setView((current) => ({
    ...current,
    longitude: ((current.longitude + x + 180) % 360 + 360) % 360 - 180,
    latitude: clamp(current.latitude + y, -89, 89),
  }));

  useEffect(() => {
    const element = surface.current;
    const observer = new ResizeObserver(([entry]) => {
      setSize([entry.contentRect.width, entry.contentRect.height]);
    });
    function wheel(event) {
      if (document.activeElement !== element && !event.ctrlKey) return;
      event.preventDefault();
      adjustZoom(event.deltaY < 0 ? 1.12 : 1 / 1.12);
    }
    observer.observe(element);
    element.addEventListener('wheel', wheel, { passive: false });
    return () => {
      observer.disconnect();
      element.removeEventListener('wheel', wheel);
    };
  }, []);

  function focusPort(id) {
    selectPort(id);
    if (!coordinates[id]) return;
    const [longitude, latitude] = coordinates[id];
    setView({ longitude, latitude, zoom: view.zoom });
  }

  function drag(event) {
    const active = pointers.current;
    const previous = active.get(event.pointerId);
    if (!previous) return;
    const current = [event.clientX, event.clientY];
    const other = [...active].find(([id]) => id !== event.pointerId)?.[1];
    active.set(event.pointerId, current);
    if (other) {
      const before = Math.hypot(previous[0] - other[0], previous[1] - other[1]);
      const after = Math.hypot(current[0] - other[0], current[1] - other[1]);
      if (before > 2 && after > 2) adjustZoom(after / before);
    } else {
      const degrees = 57.3 / (radius * view.zoom);
      rotate((previous[0] - current[0]) * degrees, (current[1] - previous[1]) * degrees);
    }
  }

  function keyboard(event) {
    if (event.target !== surface.current) return;
    switch (event.key) {
      case 'ArrowLeft': rotate(-12, 0); break;
      case 'ArrowRight': rotate(12, 0); break;
      case 'ArrowUp': rotate(0, 12); break;
      case 'ArrowDown': rotate(0, -12); break;
      case '+':
      case '=': adjustZoom(1.25); break;
      case '-': adjustZoom(.8); break;
      case 'Home': setView(home); break;
      default: return;
    }
    event.preventDefault();
  }

  const drawablePorts = ports.filter((port) => coordinates[port.port_id]);

  return <div className="globe-frame">
    <div ref={surface} className="globe-surface" tabIndex={0} role="region" aria-label="Rotatable shipping globe"
      onKeyDown={keyboard}
      onPointerDown={(event) => {
        if (event.button !== 0 || event.target.closest('[role="button"]')) return;
        if (event.pointerType === 'mouse') event.currentTarget.focus({ preventScroll: true });
        pointers.current.set(event.pointerId, [event.clientX, event.clientY]);
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={drag}
      onLostPointerCapture={(event) => pointers.current.delete(event.pointerId)}>
      <svg viewBox={`0 0 ${width} ${height}`} aria-label="World map and shipping routes">
        <defs><radialGradient id={ocean} cx="34%" cy="27%" r="74%">
          <stop offset="0%" className="globe-ocean-light" /><stop offset="100%" className="globe-ocean-dark" />
        </radialGradient>
          <marker id={direction} viewBox="0 0 10 10" refX="16" refY="5" markerWidth="8"
            markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
            <path d="M0 0L10 5L0 10Z" fill="context-stroke" />
          </marker>
        </defs>
        <path className="globe-ocean" fill={`url(#${ocean})`} d={path(sphere)} />
        <path className="globe-land" d={path(land)} />
        <path className="globe-grid" d={path(grid)} />
        {routes.map(({ route, kind }) => {
          const start = coordinates[route.from_port_id];
          const end = coordinates[route.to_port_id];
          const line = start && end && path({ type: 'LineString', coordinates: [start, end] });
          return line && <path key={route.route_id} d={line} className={'edge ' + kind}
            markerEnd={visible(end) ? `url(#${direction})` : undefined} />;
        })}
        {drawablePorts.filter((port) => visible(coordinates[port.port_id])).map((port) => {
          const id = port.port_id;
          const [x, y] = projection(coordinates[id]);
          if (x < 9 || x > width - 9 || y < 9 || y > height - 9) return null;
          const selected = portId === id;
          const affected = affectedPorts.includes(id);
          const showLabel = demo || selected || (affected && width > 420);
          const anchor = x < 85 ? 'start' : x > width - 85 ? 'end' : 'middle';
          return <g key={id} transform={`translate(${x},${y})`} role="button" tabIndex={0}
            aria-label={port.port_name} aria-pressed={selected}
            className={`globe-port${selected ? ' active' : ''}${affected ? ' affected' : ''}`}
            onClick={() => selectPort(id)} onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                selectPort(id);
              }
            }}>
            <title>{port.port_name}</title>
            <circle className="globe-port-hit" r={11} />
            <circle className="globe-port-dot" r={selected ? 6 : 4.5} />
            {showLabel && <text y={y < height - 27 ? 22 : -13} textAnchor={anchor}>{port.port_name}</text>}
          </g>;
        })}
      </svg>
    </div>
    <div className="globe-tools">
      <label className="globe-port-select"><span>Go to port</span>
        <select value={drawablePorts.some((port) => port.port_id === portId) ? portId : ''}
          onChange={(event) => focusPort(event.target.value)}>
          <option value="" disabled>Choose a port</option>
          {drawablePorts.map((port) => <option key={port.port_id} value={port.port_id}>{port.port_name}</option>)}
        </select>
      </label>
      <div className="globe-buttons">
        <button type="button" aria-label="Zoom out" disabled={view.zoom <= .75} onClick={() => adjustZoom(.8)}>−</button>
        <button type="button" aria-label="Zoom in" disabled={view.zoom >= 4} onClick={() => adjustZoom(1.25)}>+</button>
        <button type="button" onClick={() => setView(home)}>Reset view</button>
      </div>
    </div>
  </div>;
}
