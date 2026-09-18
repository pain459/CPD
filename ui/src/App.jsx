import { useCallback, useEffect, useState } from 'react';

export default function App() {
  const [jobs, setJobs] = useState([]);
  const [health, setHealth] = useState(null);
  const [msg, setMsg] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [j, h] = await Promise.all([
        fetch('/api/jobs').then((x) => x.json()),
        fetch('/api/health').then((x) => x.json()).catch(() => null),
      ]);
      setJobs(j);
      setHealth(h);
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
    setMsg(res.ok ? `queued job ${body.job_id}` : `error: ${JSON.stringify(body)}`);
    e.target.reset();
    refresh();
  }

  return (
    <main>
      <h1>CPD ETL Portal — Retail Sales (Phase 1)</h1>
      <p>Health: {health ? JSON.stringify(health) : '…'}</p>
      <form onSubmit={onUpload}>
        <input type="file" name="file" accept=".csv,.xlsx,.json" />
        <button type="submit">Upload</button>
      </form>
      <p>{msg}</p>
      <table>
        <thead><tr><th>file</th><th>status</th><th>progress</th><th>total/ok/rej</th><th>updated</th></tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td>{j.filename}</td>
              <td><span className={`pill ${j.status}`}>{j.status}</span></td>
              <td><progress value={j.progress_pct} max="100" /> {j.progress_pct}%</td>
              <td>{j.rows_total}/{j.rows_ok}/{j.rows_rejected}</td>
              <td>{j.updated_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
