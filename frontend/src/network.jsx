import React, { useState } from 'react';
import { api, cost } from './client.js';
import { Field } from './controls.jsx';

import { ShippingGlobe } from './globe.jsx';
import './globe.css';

const demoPorts = new Set(['P03', 'P05', 'P11']);
const order = ['available', 'focused', 'affected', 'chosen'];

export function Network({ ports, routes, affected, affectedPorts, selected, focusDemo }) {
  const [portId, setPortId] = useState('P05');
  const [showAll, setShowAll] = useState(false);
  const canFocusDemo = focusDemo && selected.every((id) => id === 'R04' || id === 'R06');
  const demo = canFocusDemo && !showAll;
  const visiblePorts = demo ? ports.filter((port) => demoPorts.has(port.port_id)) : ports;
  const outgoing = routes.filter((route) => route.from_port_id === portId);
  const port = ports.find((item) => item.port_id === portId);
  const style = (route) => selected.includes(route.route_id) ? 'chosen' :
    affected.includes(route.route_id) ? 'affected' : (route.from_port_id === portId ? 'focused' : 'available');
  const draw = order.flatMap((kind) => routes.filter((route) => style(route) === kind &&
    (!demo || (demoPorts.has(route.from_port_id) && demoPorts.has(route.to_port_id))))
    .map((route) => ({ route, kind })));
  return <section className="panel network">
    <div className="card-heading"><h2>Shipping network</h2>{canFocusDemo && <button className="compact" type="button" aria-pressed={showAll} onClick={() => { setShowAll(!showAll); if (showAll) setPortId('P05'); }}>{showAll ? 'Focus on demo' : 'Show all ports'}</button>}</div>
    <p className="detail">Drag to rotate and pinch or use the zoom controls. Routes are schematic.</p>
    <div className="legend" aria-label="Route legend">
      <span><i className="legend-line" /> Available</span><span><i className="legend-line affected" /> Disruption area</span>
      <span><i className="legend-line chosen" /> Selected route</span>
    </div>
    <ShippingGlobe ports={visiblePorts} routes={draw} portId={portId} selectPort={setPortId}
      demo={demo} affectedPorts={affectedPorts} />
    <div className="route-summary">
      <h3>{port ? 'Departures from ' + port.port_name : 'Select a port'}</h3>
      {outgoing.length ? <ul>{outgoing.map((route) => <li key={route.route_id}>
        <span>{route.route_id} · {ports.find((item) => item.port_id === route.to_port_id)?.port_name}</span>
        <span>{route.transit_days} days · {cost(route.cost_inr_per_container)} / container{affected.includes(route.route_id) && ' · disruption area'}</span>
      </li>)}</ul> : <p>No outgoing routes.</p>}
    </div>
  </section>;
}

export function RouteExplorer({ ports, onPath }) {
  const [query, setQuery] = useState({ origin: 'P03', destination: 'P11', objective: 'fastest', quantity_units: 10, units_per_container: 10, required_stops: [], closed_ports: [], closed_routes: [] });
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);
  const set = (key) => (event) => setQuery({ ...query, [key]: event.target.value });
  const number = (key) => (event) => setQuery({ ...query, [key]: event.target.value === '' ? '' : Number(event.target.value) });
  const ids = (key) => (event) => setQuery({ ...query, [key]: event.target.value.split(',').map((id) => id.trim().toUpperCase()).filter(Boolean) });
  return <form className="panel" onSubmit={async (event) => {
    event.preventDefault(); setPending(true); setMessage(''); onPath([]);
    try {
      const result = await api('/route', query);
      setMessage(result.no_route_reason ? 'No route. ' + result.no_route_reason :
        (result.route_ids.join(', ') || 'Same port') + ' · ' + result.total_days + ' days · ' + cost(result.freight_inr));
      onPath(result.route_ids);
    } catch (error) { setMessage(error.message); }
    finally { setPending(false); }
  }}>
    <h2>Route lookup</h2>
    <div className="route-fields">{['origin', 'destination'].map((key) =>
      <Field key={key} title={key === 'origin' ? 'Origin' : 'Destination'}><select value={query[key]} onChange={set(key)}>
        {ports.map((port) => <option key={port.port_id} value={port.port_id}>{port.port_name}</option>)}
      </select></Field>)}
      <Field title="Objective"><select value={query.objective} onChange={set('objective')}><option>fastest</option><option>cheapest</option></select></Field>
    </div>
    <div className="route-fields">
      <Field title="Quantity · units"><input required type="number" min="1" value={query.quantity_units} onChange={number('quantity_units')} /></Field>
      <Field title="Units per container"><input required type="number" min="1" value={query.units_per_container} onChange={number('units_per_container')} /></Field>
    </div>
    <details className="route-assumptions"><summary>Required stops and closures</summary>
      <div className="route-fields">
        <Field title="Required port IDs in order"><input placeholder="P05, P11" onChange={ids('required_stops')} /></Field>
        <Field title="Closed port IDs"><input placeholder="P05" onChange={ids('closed_ports')} /></Field>
        <Field title="Closed route IDs"><input placeholder="R04" onChange={ids('closed_routes')} /></Field>
      </div>
    </details>
    <button disabled={pending} type="submit">Find route</button><p role="status">{pending ? 'Finding route…' : message}</p>
  </form>;
}
