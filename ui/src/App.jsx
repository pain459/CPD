import { useCallback, useEffect, useState } from 'react';

const TERMINAL = ['COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED'];
const PALETTE = ['#4a90d9', '#50c878', '#f5a623', '#b07ce8', '#e86a6a', '#38bdf8', '#f472b6'];

/* ---------- theme ---------- */
function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('cpd-theme') || 'light');
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('cpd-theme', theme);
  }, [theme]);
  return [theme, () => setTheme((t) => (t === 'light' ? 'dark' : 'light'))];
}

/* ---------- brand ---------- */
function Logo() {
  return (
    <span className="brand">
      <svg viewBox="0 0 44 44" width="36" height="36" aria-hidden="true">
        <defs>
          <linearGradient id="cpd-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4a90d9" />
            <stop offset="1" stopColor="#7b5cd6" />
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="40" height="40" rx="10" fill="url(#cpd-g)" />
        <path d="M10 29V15h9M34 15v14h-9" stroke="#fff" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="22" cy="22" r="2.6" fill="#fff" />
      </svg>
      <span className="brand-text"><strong>CPD</strong><small>Client Data Portal</small></span>
    </span>
  );
}

function ThemeToggle({ theme, onToggle }) {
  return (
    <button className="btn ghost" onClick={onToggle} title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}>
      {theme === 'light' ? (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
      )}
      {theme === 'light' ? 'Dark' : 'Light'}
    </button>
  );
}

/* ---------- charts (dependency-free SVG) ---------- */
function BarsChart({ data }) {
  // data: [{label, value}]
  if (!data.length) return <p className="muted">No data yet.</p>;
  const max = Math.max(...data.map((d) => d.value), 1);
  const W = 560, H = 220, padL = 8, padB = 44, padT = 12;
  const bw = (W - padL * 2) / data.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img">
      {data.map((d, i) => {
        const h = ((H - padB - padT) * d.value) / max;
        const x = padL + i * bw + bw * 0.18;
        return (
          <g key={d.label}>
            <title>{`${d.label}: $${d.value.toLocaleString()}`}</title>
            <rect x={x} y={H - padB - h} width={bw * 0.64} height={h} rx="3" className="bar" />
            {data.length <= 16 && (
              <text x={x + bw * 0.32} y={H - padB + 14} textAnchor="middle" className="axis">
                {d.label.slice(5)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function Donut({ parts, size = 170 }) {
  // parts: [{label, value, color}]
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const R = 54, C = 2 * Math.PI * R;
  let acc = 0;
  return (
    <div className="donut-wrap">
      <svg viewBox="0 0 140 140" width={size} height={size} role="img">
        <circle cx="70" cy="70" r={R} fill="none" strokeWidth="18" className="donut-track" />
        {parts.map((p) => {
          const len = (p.value / total) * C;
          const el = (
            <circle key={p.label} cx="70" cy="70" r={R} fill="none" stroke={p.color}
              strokeWidth="18" strokeDasharray={`${len} ${C - len}`}
              strokeDashoffset={-acc} transform="rotate(-90 70 70)">
              <title>{`${p.label}: ${p.value.toLocaleString()}`}</title>
            </circle>
          );
          acc += len;
          return el;
        })}
        <text x="70" y="66" textAnchor="middle" className="donut-total">{total.toLocaleString()}</text>
        <text x="70" y="84" textAnchor="middle" className="axis">total</text>
      </svg>
      <ul className="legend">
        {parts.map((p) => (
          <li key={p.label}><i style={{ background: p.color }} />{p.label} — {p.value.toLocaleString()}</li>
        ))}
      </ul>
    </div>
  );
}

/* ---------- job detail (live SSE) ---------- */
function JobDetail({ job, onClose }) {
  const [detail, setDetail] = useState(null);
  const [rows, setRows] = useState([]);
  const [live, setLive] = useState(true);
  useEffect(() => {
    let es;
    const fallback = () => {
      fetch(`/api/jobs/${job.id}`).then((x) => x.json()).then((d) => { setDetail(d); setLive(false); });
    };
    try {
      es = new EventSource(`/api/jobs/${job.id}/events`);
      es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.error) { es.close(); fallback(); return; }
        setDetail(d);
        if (TERMINAL.includes(d.status)) {
          es.close();
          setLive(false);
          fetch(`/api/jobs/${job.id}/rows?limit=20`).then((x) => x.json()).then(setRows).catch(() => setRows([]));
        }
      };
      es.onerror = () => { es.close(); fallback(); };
    } catch {
      fallback();
    }
    return () => es && es.close();
  }, [job.id]);
  if (!detail) return <section className="card"><p>Loading job…</p></section>;
  const breakdown = Object.entries(detail.error_breakdown || {});
  const maxErr = Math.max(0, ...breakdown.map(([, v]) => v));
  return (
    <section className="card">
      <div className="row-between">
        <h2>{detail.filename}</h2>
        <button className="btn ghost" onClick={onClose}>Close</button>
      </div>
      <p>
        <span className={`pill ${detail.status}`}>{detail.status.replaceAll('_', ' ')}</span>
        {live && <span className="live-dot" title="live updates" />}
        <span className="muted"> {detail.rows_total} total · {detail.rows_ok} loaded · {detail.rows_rejected} quarantined</span>
      </p>
      <p><progress value={detail.progress_pct} max="100" /> {detail.progress_pct}%</p>
      {detail.error_summary && <p className="muted">{detail.error_summary}</p>}
      <p className="downloads">
        <a className="btn" href={`/api/jobs/${job.id}/raw`}>Raw file</a>
        {breakdown.length > 0 && <a className="btn" href={`/api/jobs/${job.id}/errors.csv`}>Quarantine CSV</a>}
      </p>
      {breakdown.length > 0 && (
        <>
          <h3>Quarantine reasons</h3>
          {breakdown.map(([reason, n]) => (
            <div className="bar-row" key={reason}>
              <span className="bar-label">{reason}</span>
              <div className="bar-track"><div className="bar-fill warn" style={{ width: `${(n / maxErr) * 100}%` }} /></div>
              <span className="bar-value">{n}</span>
            </div>
          ))}
        </>
      )}
      {rows.length > 0 && (
        <>
          <h3>Loaded sample (first {rows.length})</h3>
          <div className="table-wrap"><table>
            <thead><tr><th>Order</th><th>Date</th><th>Store</th><th>SKU</th><th>Qty</th><th>Total USD</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.order_id}>
                  <td>{row.order_id}</td><td>{row.order_date}</td><td>{row.store_id}</td>
                  <td>{row.sku}</td><td>{row.qty}</td><td>${row.line_total_usd}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </>
      )}
    </section>
  );
}

/* ---------- app ---------- */
export default function App() {
  const [theme, toggleTheme] = useTheme();
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
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  async function onUpload(e) {
    e.preventDefault();
    const f = new FormData(e.target).get('file');
    if (!f || !f.name) return;
    const fd = new FormData();
    fd.append('file', f);
    setMsg('Uploading…');
    const res = await fetch('/api/uploads', { method: 'POST', body: fd });
    const body = await res.json();
    setMsg(res.ok ? `Queued ${f.name} as job ${body.job_id.slice(0, 8)}…${body.deduped ? ' (already processed — deduplicated)' : ''}` : `Upload failed: ${JSON.stringify(body)}`);
    e.target.reset();
    refresh();
  }

  const healthy = health?.status === 'ok';
  const statusCounts = {};
  jobs.forEach((j) => { statusCounts[j.status] = (statusCounts[j.status] || 0) + 1; });
  const statusParts = [
    { label: 'Loaded clean', value: statusCounts.COMPLETED || 0, color: '#50c878' },
    { label: 'With quarantine', value: statusCounts.COMPLETED_WITH_ERRORS || 0, color: '#f5a623' },
    { label: 'Failed', value: statusCounts.FAILED || 0, color: '#e86a6a' },
    { label: 'Running', value: jobs.length - (statusCounts.COMPLETED || 0) - (statusCounts.COMPLETED_WITH_ERRORS || 0) - (statusCounts.FAILED || 0), color: '#4a90d9' },
  ].filter((p) => p.value > 0);
  const dayData = (summary?.by_day || []).map((d) => ({ label: d.date, value: Number(d.revenue_usd) }));
  const catParts = (summary?.by_category || []).map((c, i) => ({ label: c.category, value: Number(c.revenue_usd), color: PALETTE[i % PALETTE.length] }));
  const quarantined = jobs.reduce((a, j) => a + j.rows_rejected, 0);

  return (
    <div className="page">
      <header className="topbar">
        <Logo />
        <div className="topbar-right">
          <span className={`health ${healthy ? 'ok' : 'bad'}`} title={health ? JSON.stringify(health.checks) : 'loading'}>
            {healthy ? 'All systems operational' : 'Checking systems…'}
          </span>
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
        </div>
      </header>

      <section className="hero card">
        <div>
          <h1>Client Data Ingestion Portal</h1>
          <p>
            Upload sales files in <strong>CSV, JSON, or Excel</strong> format. CPD validates every row,
            normalizes currencies to USD, loads clean data into the warehouse, and quarantines
            problematic rows with machine-readable reasons. Raw files are archived to S3 object
            storage, and every job can be tracked live below — from upload to loaded.
          </p>
        </div>
        <form className="upload" onSubmit={onUpload}>
          <input type="file" name="file" accept=".csv,.xlsx,.json" aria-label="Data file" />
          <button className="btn primary" type="submit">Upload &amp; ingest</button>
          {msg && <p className="muted">{msg}</p>}
        </form>
      </section>

      <section className="kpis">
        <div className="card kpi"><small>Orders loaded</small><strong>{(summary?.orders ?? 0).toLocaleString()}</strong></div>
        <div className="card kpi"><small>Revenue (USD)</small><strong>${Number(summary?.revenue_usd ?? 0).toLocaleString()}</strong></div>
        <div className="card kpi"><small>Jobs processed</small><strong>{jobs.length}</strong></div>
        <div className="card kpi"><small>Rows quarantined</small><strong>{quarantined.toLocaleString()}</strong></div>
      </section>

      <section className="grid">
        <div className="card">
          <h2>Revenue by day (USD)</h2>
          <BarsChart data={dayData} />
        </div>
        <div className="card">
          <h2>Revenue share by category</h2>
          {catParts.length ? <Donut parts={catParts} /> : <p className="muted">No data yet.</p>}
        </div>
        <div className="card">
          <h2>Job outcomes</h2>
          {statusParts.length ? <Donut parts={statusParts} /> : <p className="muted">No jobs yet — upload a file to get started.</p>}
        </div>
      </section>

      <section className="card">
        <h2>Ingestion jobs</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>File</th><th>Status</th><th>Progress</th><th>Total / Loaded / Quarantined</th><th>Updated</th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} onClick={() => setSelected(j)} className="clickable">
                <td>{j.filename}</td>
                <td><span className={`pill ${j.status}`}>{j.status.replaceAll('_', ' ')}</span></td>
                <td><progress value={j.progress_pct} max="100" /> {j.progress_pct}%</td>
                <td>{j.rows_total} / {j.rows_ok} / {j.rows_rejected}</td>
                <td>{new Date(j.updated_at).toLocaleString()}</td>
              </tr>
            ))}
            {!jobs.length && <tr><td colSpan="5" className="muted">No jobs yet.</td></tr>}
          </tbody>
        </table></div>
      </section>

      {selected && <JobDetail job={selected} onClose={() => setSelected(null)} />}

      <footer className="muted">CPD Data Platform · uploads are deduplicated, archived to S3, and never double-counted.</footer>
    </div>
  );
}
