import React, { useState } from 'react';
import { api, label } from './client.js';

export function Advisories({ events, report, choose, replay }) {
  const [news, setNews] = useState(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function loadNews() {
    setPending(true); setError('');
    try { setNews(await api('/news')); } catch (issue) { setError(issue.message); }
    finally { setPending(false); }
  }
  return <>
    <section className="panel"><h2>Sample disruptions</h2>
      <p>{report.events.length ? 'Applied · ' + report.events.map((event) => event.event_id).join(', ') : 'No active scenario events.'}</p>
      <div className="event-list">{events.map((event) => <article key={event.event_id}>
        <div><h3>{event.headline.replace(/^Synthetic: /, '')}</h3>
          <p>{event.reported_date} · {event.port_id} · {event.port_status} · {event.expected_duration_days} days</p></div>
        <button onClick={() => choose(event.event_id, event.reported_date)}>Choose {event.event_id}</button>
      </article>)}</div>
    </section>
    <section className="panel"><h2>Public advisories</h2>
      <p>Review published items separately from the fictional shipment timeline. Replay uses the simulated date and requires your own duration and severity assumptions.</p>
      <button onClick={loadNews} disabled={pending}>{pending ? 'Loading advisories…' : 'Fetch public advisories'}</button>
      {error && <p role="alert">{error}</p>}
      {news?.errors.map((issue) => <p className="detail" key={issue}>{issue}</p>)}
      {news && !news.articles.length && <p>No matching disruption candidates.</p>}
      {news?.articles.map((item) => <article className="advisory" key={item.url}>
        <h3><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a></h3>
        <p>{item.source} · {item.published ?? 'Timestamp unknown'} · {item.candidate.confidence}</p>
        <p>{label(item.candidate.event_type ?? 'Unknown event')} · {item.candidate.port_id ?? 'Port unknown'} · Duration and severity unknown</p>
        <button disabled={!item.candidate.port_id || !item.candidate.event_type} onClick={() => replay(item.candidate)}>Review as simulated replay</button>
      </article>)}
    </section>
  </>;
}
