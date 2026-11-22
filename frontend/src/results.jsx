import React from 'react';
import { cost } from './client.js';

export function Metrics({ report }) {
  const values = [
    ['Total shipments', report.total_shipments], ['Affected shipments', report.affected_shipment_ids.length],
    ['Contracts at risk', report.urgent_contract_ids.length], ['Estimated penalties', cost(report.estimated_penalties_inr)],
  ];
  return <dl className="metrics">{values.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>;
}

export function ImpactRail({ report, compare }) {
  const delivery = report.cascade.find((task) => task.task_id === 'delivery');
  const urgent = report.impacts.find((impact) => impact.contract_id === report.urgent_contract_ids[0]);
  const shipment = urgent ?? report.impacts[0];
  const actual = delivery?.revised.finish ?? shipment?.revised_eta;
  const deadline = report.customer_deadline ?? shipment?.deadline;
  const planned = delivery?.baseline.finish ?? shipment?.baseline_eta;
  const late = actual && deadline && actual > deadline;
  return <aside className="impact-rail" aria-label="Scenario outcome">
    <section className="panel metrics-panel"><h2>Impact metrics</h2><Metrics report={report} /></section>
    <section className="panel contract-card">
      <div className="card-heading"><h2>Contract timeline</h2>
        <span className={'status-chip ' + (late ? 'late' : 'safe')}>{late ? 'Late delivery' : actual ? 'On schedule' : 'Baseline'}</span></div>
      {actual ? <>
        <p className="detail">{report.manufacturing ? 'DEMO-CUSTOMER' : shipment.contract_id}</p>
        <dl className="eta-pair"><div><dt>Planned ETA</dt><dd>{planned}</dd></div>
          <div className={late ? 'late' : ''}><dt>Revised ETA</dt><dd>{actual}</dd></div></dl>
        <p className="detail">Deadline · {deadline}</p>
      </> : <p className="detail">Apply an event to see affected contracts.</p>}
      <button className="primary compare" type="button" onClick={compare}>Compare recovery options</button>
    </section>
  </aside>;
}

export function Timeline({ report, chosen }) {
  const rows = report.cascade.length ? report.cascade.map((task) => ({
    key: task.task_id, title: task.label, plan: task.baseline.finish, revised: task.revised.finish,
    deadline: task.task_id === 'delivery' ? report.customer_deadline : null,
    directDays: task.direct_delay_days,
    reasons: task.revised.finish !== task.baseline.finish ? task.reason_paths : [],
  })) : report.impacts.map((impact) => ({
    key: impact.shipment_id, title: impact.shipment_id + ' · ' + impact.contract_id,
    plan: impact.baseline_eta, revised: impact.revised_eta, deadline: impact.deadline,
  }));
  return <section className="panel"><h2>Delivery timeline</h2>
    {!rows.length && <p>No scheduled calls match the current scenario.</p>}
    <div className="timeline">{rows.map((row) => <article key={row.key}>
      <h3>{row.title}</h3>
      <dl><div><dt>Planned</dt><dd>{row.plan}</dd></div><div><dt>Revised</dt><dd className={row.plan !== row.revised ? 'changed' : ''}>{row.revised}</dd></div>
        {row.deadline && <div><dt>Deadline</dt><dd>{row.deadline}</dd></div>}
        {chosen?.eta && row.deadline && (report.manufacturing || row.key === chosen.shipment_id) &&
          <div><dt>Selected recovery</dt><dd>{chosen.eta}</dd></div>}
      </dl>
      {row.reasons?.length > 0 && <p className="detail">{row.directDays ? 'Direct port wait · ' + row.directDays + ' days · ' : 'Downstream delay · '}{row.reasons.map((path) => path.join(' → ')).join(' / ')}</p>}
    </article>)}</div>
  </section>;
}

export function Recovery({ report, selected, select }) {
  return <section className="panel"><h2>Recovery options</h2>
    {!report.recovery.length && <p>Apply an event that affects a shipment to compare recovery options.</p>}
    {report.recovery.map((item) => <article className="recovery-item" key={item.shipment_id}>
      <h3>{item.contract_id} · {item.shipment_id}</h3>
      <p>{item.recommended_id ? 'Recommended · ' + item.recommended_id : 'No feasible recovery option.'}
        {item.recommended_id && !item.deadline_feasible && ' · No option meets the deadline.'}</p>
      <div className="scroll-table" role="region" aria-label="Recovery comparison table" tabIndex={0}><table><thead><tr><th>Option</th><th>Status</th><th>Delivery ETA</th><th>Freight</th><th>Purchase</th><th>Penalty</th><th>Future cost</th><th>Reason</th></tr></thead>
        <tbody>{item.options.filter((option) => option.status !== 'rejected').map((option) =>
          <tr key={option.option_id} className={option.option_id === item.recommended_id ? 'recommended' : ''}>
            <th><button type="button" className="text-button"
              aria-pressed={selected?.option_id === option.option_id && selected?.shipment_id === item.shipment_id}
              onClick={() => select({ ...option, shipment_id: item.shipment_id })}>{option.option_id}</button>
              <span className="detail">{option.kind}</span></th>
            <td>{option.status}</td><td>{option.eta ?? '—'}</td><td>{cost(option.freight_inr)}</td>
            <td>{cost(option.purchase_inr)}</td><td>{cost(option.penalty_inr)}</td><td>{cost(option.total_future_inr)}</td><td>{option.reason}</td>
          </tr>)}</tbody></table></div>
      {item.options.some((option) => option.status === 'rejected') && <details><summary>Rejected options and reasons</summary>
        <ul>{item.options.filter((option) => option.status === 'rejected').map((option) =>
          <li key={option.option_id}>{option.option_id} · {option.reason}</li>)}</ul></details>}
      <ul className="detail">{item.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
    </article>)}
  </section>;
}

export function Shipments({ report, shipments, choose }) {
  return <section className="panel"><h2>Shipments and contracts</h2>
    {report.impacts.map((impact) => <article className="impact" key={impact.shipment_id}><h3>{impact.shipment_id} · {impact.contract_id}</h3>
      <p>{impact.baseline_eta} → {impact.revised_eta} · {impact.late_days} days late</p>
      <ul>{impact.calls.map((call, index) => <li key={index}>{call.status} · {call.port_id} {call.call_type} · {call.call_date} · {call.wait_days} days wait</li>)}</ul>
    </article>)}
    {report.manufacturing ? <p>DEMO-RAW and DEMO-FINISHED appear in the manufacturing delivery timeline.</p> :
      <div className="scroll-table" role="region" aria-label="Shipment records table" tabIndex={0}><table><thead><tr><th>Shipment</th><th>Endpoints</th><th>Contract</th><th>Planned ETA</th><th>Deadline</th></tr></thead>
        <tbody>{shipments.map(({ shipment, contract }) => <tr key={shipment.shipment_id}>
          <th><button className="text-button" onClick={() => choose(shipment.shipment_id)}>{shipment.shipment_id}</button></th>
          <td>{shipment.origin_port_id} → {shipment.destination_port_id}</td><td>{contract.contract_id}</td>
          <td>{shipment.planned_arrival_date}</td><td>{contract.deadline}</td>
        </tr>)}</tbody></table></div>}
  </section>;
}
