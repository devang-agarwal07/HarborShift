import React, { useEffect, useLayoutEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, label } from './client.js';
import { Network, RouteExplorer } from './network.jsx';
import { Controls, initial } from './controls.jsx';
import { ImpactRail, Recovery, Shipments, Timeline } from './results.jsx';
import { Advisories } from './advisories.jsx';
import './style.css';
import './theme.css';

const views = ['Overview', 'Network', 'Shipments', 'Disruptions', 'Recovery'];

const themeKey = 'harborshift-theme';

function initialTheme() {
  try {
    return localStorage.getItem(themeKey) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

function ThemeToggle({ theme, toggle }) {
  const dark = theme === 'dark';
  return <button type="button" className="theme-toggle" aria-label="Dark theme" aria-pressed={dark}
    title={dark ? 'Switch to light theme' : 'Switch to dark theme'} onClick={toggle}>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {dark ? <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19m0-14-1.5 1.5m-11 11L5 19" /></>
        : <path d="M20.5 15.2A8.8 8.8 0 0 1 8.8 3.5 8.8 8.8 0 1 0 20.5 15.2Z" />}
    </svg>
    <span>{dark ? 'Light' : 'Dark'}</span>
  </button>;
}

function App() {
  const [theme, setTheme] = useState(initialTheme);
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      localStorage.setItem(themeKey, next);
    } catch {
      // The switch still works when storage is unavailable.
    }
  }

  const [view, setView] = useState('Overview');
  const [form, setForm] = useState(initial);
  const [data, setData] = useState(null);
  const [report, setReport] = useState(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);
  const [path, setPath] = useState([]);
  const [replay, setReplay] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([api('/ports'), api('/routes'), api('/shipments'), api('/disruptions'),
      api('/simulate', { as_of: initial.as_of, manufacturing: initial.manufacturing })])
      .then(([ports, routes, shipments, events, baseline]) => {
        if (active) { setData({ ports, routes, shipments, events }); setReport(baseline); }
      })
      .catch((issue) => { if (active) setError(issue.message); })
      .finally(() => { if (active) setPending(false); });
    return () => { active = false; };
  }, [revision]);

  async function simulate(apply) {
    setPending(true); setError('');
    const query = {
      as_of: form.as_of || report.as_of, manufacturing: form.manufacturing, shipment_id: form.shipment_id || null,
      units_per_container: apply ? form.units_per_container : undefined, use_ml: apply && form.use_ml,
      congestion: apply && form.use_ml ? form.congestion : 0, buffer_days: apply && form.use_ml ? form.buffer_days : 0,
      original_purchase_inr: apply && !form.manufacturing && form.shipment_id ? form.purchase || null : null,
    };
    if (apply && form.sample !== 'manual') query.sample_ids = [form.sample];
    if (apply && form.sample === 'manual') {
      query.event = {
        start: form.start || null, port_id: form.port_id, event_type: form.event_type, duration_days: form.duration_days,
        severity: form.severity, port_status: form.port_status, advisory_replay: replay,
      };
    }
    try {
      setReport(await api('/simulate', query)); setSelected(null); setPath([]);
      if (!apply) setReplay(false);
    } catch (issue) { setError(issue.message); }
    finally { setPending(false); }
  }

  const network = data && report && <Network ports={data.ports} routes={data.routes}
    affected={report.affected_edge_ids} affectedPorts={report.affected_port_ids}
    selected={selected?.route_ids ?? path} focusDemo={view === 'Overview' && report.manufacturing} />;
  return <>
    <header className="topbar">
      <div className="brand"><span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M3 16h18l-3 4H6zM7 16V9h10v7M10 9V5h4v4M3 22c2-1 4-1 6 0 2-1 4-1 6 0 2-1 4-1 6 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg></span><span>HarborShift</span></div>
      <nav aria-label="Main navigation">{views.map((mode) =>
        <button key={mode} aria-current={view === mode ? 'page' : undefined} onClick={() => setView(mode)}>{mode}</button>)}</nav>
      <div className="header-actions"><span className="data-tag">Synthetic data</span>
        <ThemeToggle theme={theme} toggle={toggleTheme} /></div>
    </header>
    <main>
      <div className="page-heading"><div><h1>{view === 'Overview' ? 'Disruption simulator' : view === 'Network' ? 'Transport network' : view}</h1>
        <p>{report ? (report.manufacturing ? 'Manufacturing demo' : 'Sample shipments') + ' · ' + report.as_of : 'HarborShift offline scenario workspace'}</p></div>
        {report?.events.some((event) => event.source.startsWith('advisory replay')) && <span className="model-tag">Simulated advisory replay</span>}
        {report && <span className="model-tag">{report.prediction.sources.map((source) => source === 'rule_fallback' ? 'Rule-based estimate' : label(source)).join(' + ')}</span>}
      </div>
      {error && <div className="notice" role="alert">{error}
        {!data && <button onClick={() => { setPending(true); setError(''); setRevision(revision + 1); }}>Retry</button>}</div>}
      {pending && <p className="loading" role="status">{data ? 'Running scenario…' : 'Loading HarborShift…'}</p>}
      {data && report && <>
        {view === 'Overview' && <>
          <div className="workbench">
            <aside>{replay && <p className="notice">Advisory replay. Review the port and event type, then enter your own severity and duration.</p>}
              <Controls form={form} setForm={setForm} {...data} pending={pending}
                apply={() => simulate(true)} reset={() => simulate(false)} /></aside>
            <div className="network-column">{network}</div>
            <ImpactRail report={report} compare={() => setView('Recovery')} />
          </div>
          <div className="overview-details"><Timeline report={report} chosen={selected} /><Recovery report={report} selected={selected} select={setSelected} /></div>
        </>}
        {view === 'Network' && <div className="stack">{network}<RouteExplorer ports={data.ports} onPath={(ids) => { setSelected(null); setPath(ids); }} /></div>}
        {view === 'Shipments' && <Shipments report={report} shipments={data.shipments} choose={(shipment_id) => {
          setForm({ ...form, manufacturing: false, shipment_id, purchase: '' }); setView('Overview');
        }} />}
        {view === 'Disruptions' && <div className="stack"><Advisories events={data.events} report={report}
          choose={(sample, as_of) => { setReplay(false); setForm({ ...form, sample, as_of }); setView('Overview'); }}
          replay={(candidate) => { setReplay(true); setForm({ ...form, sample: 'manual', port_id: candidate.port_id,
            event_type: candidate.event_type, start: '', duration_days: '', severity: '', port_status: 'restricted' }); setView('Overview'); }} /></div>}
        {view === 'Recovery' && <div className="stack"><Recovery report={report} selected={selected} select={setSelected} />
          <Timeline report={report} chosen={selected} /></div>}
        <details className="warnings"><summary>Scenario notes</summary><ul>{report.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>
      </>}
    </main>
  </>;
}

createRoot(document.getElementById('root')).render(<App />);
