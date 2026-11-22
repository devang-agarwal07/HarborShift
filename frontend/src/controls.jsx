import React from 'react';
import { eventTypes, label } from './client.js';

export const initial = {
  as_of: '2027-01-05', sample: 'E001', manufacturing: true, shipment_id: '',
  port_id: 'P05', event_type: 'strike', duration_days: 5, severity: 4,
  port_status: 'closed', start: '', purchase: '', units_per_container: 10, use_ml: false, congestion: 0, buffer_days: 0,
};

export function Field({ title, children }) {
  return <label className="field"><span>{title}</span>{children}</label>;
}

export function Controls({ form, setForm, ports, events, shipments, pending, apply, reset }) {
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  const number = (key) => (event) => setForm({ ...form, [key]: event.target.value === '' ? '' : Number(event.target.value) });
  const sample = events.find((event) => event.event_id === form.sample);
  const selectedShipment = shipments.find(({ shipment }) => shipment.shipment_id === form.shipment_id)?.shipment;
  return <form className="panel controls" onSubmit={(event) => { event.preventDefault(); apply(); }}>
    <h2>Scenario controls</h2>
    <Field title="Dataset"><select value={form.manufacturing ? 'demo' : 'sample'} onChange={(event) =>
      setForm({ ...form, manufacturing: event.target.value === 'demo', shipment_id: '', purchase: '' })}>
      <option value="demo">Manufacturing demo</option><option value="sample">Sample shipments</option>
    </select></Field>
    {!form.manufacturing && <Field title="Shipment"><select value={form.shipment_id} onChange={(event) => setForm({ ...form, shipment_id: event.target.value, purchase: '' })}>
      <option value="">All shipments</option>{shipments.map(({ shipment }) =>
        <option key={shipment.shipment_id} value={shipment.shipment_id}>{shipment.shipment_id} · {shipment.contract_id}</option>)}
    </select></Field>}
    <Field title="Disruption"><select value={form.sample} onChange={(event) => {
      const saved = events.find((item) => item.event_id === event.target.value);
      setForm({ ...form, sample: event.target.value, as_of: saved?.reported_date ?? form.as_of });
    }}>
      {events.map((event) => <option key={event.event_id} value={event.event_id}>
        {event.event_id} · {label(event.event_type)} · {ports.find((port) => port.port_id === event.port_id)?.port_name}
      </option>)}<option value="manual">Manual event</option>
    </select></Field>
    <Field title="Simulated date"><input type="date" required value={form.as_of} onChange={set('as_of')} /></Field>
    {sample && <div className="event-preview"><strong>{sample.headline.replace(/^Synthetic: /, '')}</strong>
      <span>{sample.expected_duration_days} days · severity {sample.severity_1_to_5}/5 · {sample.port_status}</span></div>}
    {form.sample === 'manual' && <>
      <Field title="Port"><select value={form.port_id} onChange={set('port_id')}>
        {ports.map((port) => <option key={port.port_id} value={port.port_id}>{port.port_name}</option>)}
      </select></Field>
      <Field title="Event type"><select value={form.event_type} onChange={set('event_type')}>
        {eventTypes.map((type) => <option key={type} value={type}>{label(type)}</option>)}
      </select></Field>
      <Field title="Port status"><select value={form.port_status} onChange={set('port_status')}>
        <option value="closed">Closed</option><option value="restricted">Restricted</option>
      </select></Field>
      <Field title="Event start (optional)"><input type="date" value={form.start} onChange={set('start')} /></Field>
      <Field title="Duration · days"><input type="number" min="0" required value={form.duration_days} onChange={number('duration_days')} /></Field>
      <Field title="Severity · 1–5"><input type="number" min="1" max="5" required value={form.severity} onChange={number('severity')} /></Field>
    </>}
    <details><summary>Packing and delay assumptions</summary>
      <Field title="Units per container"><input type="number" min="1" required value={form.units_per_container} onChange={number('units_per_container')} /></Field>
      {selectedShipment && form.units_per_container > 0 && <p className="detail">{Math.ceil(selectedShipment.quantity_units / form.units_per_container)} container(s) for {selectedShipment.quantity_units} units</p>}
      {selectedShipment && <Field title="Original purchase cost · INR"><input type="number" min="0" step="0.01" value={form.purchase} onChange={set('purchase')} placeholder="Unknown" /></Field>}
      <label className="check"><input type="checkbox" checked={form.use_ml} onChange={(event) =>
        setForm({ ...form, use_ml: event.target.checked })} /> Use synthetic ML for restrictions</label>
      {form.use_ml && <>
        <Field title="Congestion · 0–5"><input type="number" min="0" max="5" required value={form.congestion} onChange={number('congestion')} /></Field>
        <Field title="Schedule buffer · days"><input type="number" min="0" required value={form.buffer_days} onChange={number('buffer_days')} /></Field>
      </>}
    </details>
    <div className="actions"><button className="primary" disabled={pending} type="submit">Apply event</button>
      <button disabled={pending} type="button" onClick={reset}>Reset</button></div>
  </form>;
}
