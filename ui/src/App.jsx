import { useCallback, useEffect, useState } from 'react';

function Bar({ value, max, label }) {
  return (
    <div className="bar-row">
      <span className="bar-label">{label}</span>
      <div className="bar-track"><div className="bar-fill" style={{ width: `${max ? (value / max) * 100 : 0}%` }} /></div>
      <span className="bar-value">{value}</span>
    </div>
  );
}

function JobDetail({ job, onClose }) {
  const [detail, setDetail] = useState(null);
  const [rows, setRows] = useState([]);
  useEffect(() => {
    fetch(`/api/jobs/${job.id}`).then((x) => x.json()).then(setDetail);
    fetch(`/api/jobs/${job.id}/rows?limit=20`).then((x) => x.json()).then(setRows).catch(() => setRows([]));
  }, [job.id]);
  if (!detail) return <section><p>loading…</p></section>;
  const breakdown = Object.entries(detail.error_breakdown || {});
  const maxErr = Math.max(0, ...breakdown.map(([, v]) => v));
  return (
    <section className="detail">
      <h2>{detail.filename} <button onClick={onClose}>close</button></h2>
      <p>Status: <span className={`pill ${detail.status}`}>{detail.status}</span> — {detail.rows_total} total / {detail.rows_ok} ok / {detail.rows_rejected} rejected</p>
      {detail.error_summary && <p className="muted">{detail.error_summary}</p>}
      {breakdown.length > 0 && (
        <>
          <h3>Rejection reasons</h3>
          {breakdown.map(([reason, n]) => <Bar key={reason} value={n} max={maxErr} label={reason} />)}
          <p><a href={`/api/jobs/${job.id}/errors.csv`}>download errors.csv</a></p>
        </>
      )}
      {rows.length > 0 && (
        <>
          <h3>Loaded rows (first {rows.length})</h3>
          <table>
            <thead><tr><th>order</th><th>date</th><th>store</th><th>sku</th><th>qty</th><th>total USD</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.order_id}>
                  <td>{r.order_id}</td><td>{r.order_date}</td><td>{r.store_id}</td>
                  <td>{r.sku}</td><td>{r.qty}</td><td>{r.line_total_usd}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

export default function App() {
  const [jobs, setJobs] = useState([]);
  const [health, setHealth] = useState(null);
  const [summary, setSummary] = useState(null);
  const [selected, setSelected] = useState(null);
  const [msg, setMsg] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [j, h, s] = await Promise.all([
        fetch('/api/jobs').then((x) => x.json()),
        fetch('/api/health').then((x) => x.json()).catch(() => null),
        fetch('/api/sales/summary').then((x) => x.json()).catch(() => null),
      ]);
      setJobs(j);
      setHealth(h);
      setSummary(s);
    } catch (e) {
      setMsg(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  async function onUpload(e) {
    e.preventDefault();
    const f = new FormData(e.target).get('file');
    if (!f || !f.name) return;
    const fd = new FormData();
    fd.append('file', f);
    setMsg('uploading…');
    const res = await fetch('/api/uploads', { method: 'POST', body: fd });
    const body = await res.json();
    setMsg(res.ok ? `queued job ${body.job_id}${body.deduped ? ' (deduped)' : ''}` : `error: ${JSON.stringify(body)}`);
    e.target.reset();
    refresh();
  }

  const maxDay = Math.max(0, ...(summary?.by_day || []).map((d) => Number(d.revenue_usd)));

  return (
    <main>
      <h1>CPD ETL Portal — Retail Sales (Phase 2)</h1>
      <p>Health: {health ? JSON.stringify(health) : '…'}</p>
      <form onSubmit={onUpload}>
        <input type="file" name="file" accept=".csv,.xlsx,.json" />
        <button type="submit">Upload</button>
      </form>
      <p>{msg}</p>

      {summary && (
        <section>
          <h2>Sales summary — {summary.orders} orders, ${summary.revenue_usd} revenue (USD)</h2>
          {(summary.by_day || []).map((d) => (
            <Bar key={d.date} value={Number(d.revenue_usd)} max={maxDay} label={`${d.date} (${d.orders})`} />
          ))}
          <h3>By category</h3>
          <table>
            <thead><tr><th>category</th><th>orders</th><th>revenue USD</th></tr></thead>
            <tbody>
              {(summary.by_category || []).map((c) => (
                <tr key={c.category}><td>{c.category}</td><td>{c.orders}</td><td>{c.revenue_usd}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <h2>Jobs</h2>
      <table>
        <thead><tr><th>file</th><th>status</th><th>progress</th><th>total/ok/rej</th><th>updated</th></tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} onClick={() => setSelected(j)} className="clickable">
              <td>{j.filename}</td>
              <td><span className={`pill ${j.status}`}>{j.status}</span></td>
              <td><progress value={j.progress_pct} max="100" /> {j.progress_pct}%</td>
              <td>{j.rows_total}/{j.rows_ok}/{j.rows_rejected}</td>
              <td>{j.updated_at}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected && <JobDetail job={selected} onClose={() => setSelected(null)} />}
    </main>
  );
}
