//! Local SQLite telemetry with bounded raw retention and durable aggregates.
//! Data points are measured by the native sampler, not model-generated.
use rusqlite::{params, Connection};
use serde::Serialize;
use std::path::Path;
use std::sync::Mutex;

#[derive(Clone, Serialize)]
pub struct MetricPoint {
    pub timestamp: i64,
    pub cpu: Option<f64>,
    pub ram: Option<f64>,
    pub gpu: Option<f64>,
    pub gpu_temp: Option<f64>,
    pub vram_mb: Option<f64>,
}

pub struct TelemetryStore(pub Mutex<Connection>);

impl TelemetryStore {
    pub fn open(directory: &Path) -> Result<Self, String> {
        std::fs::create_dir_all(directory).map_err(|_| "Cannot create telemetry directory")?;
        let path = directory.join("telemetry.sqlite3");
        let conn = Connection::open(path).map_err(|e| e.to_string())?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA busy_timeout=5000;
             CREATE TABLE IF NOT EXISTS raw_telemetry(
               ts INTEGER NOT NULL, cpu REAL, ram REAL, gpu REAL, gpu_temp REAL, vram_mb REAL
             );
             CREATE INDEX IF NOT EXISTS idx_raw_time ON raw_telemetry(ts);
             CREATE TABLE IF NOT EXISTS minute_telemetry(
               bucket INTEGER PRIMARY KEY, samples INTEGER NOT NULL,
               cpu_total REAL NOT NULL, ram_total REAL NOT NULL,
               gpu_total REAL NOT NULL, gpu_count INTEGER NOT NULL,
               temp_total REAL NOT NULL, temp_count INTEGER NOT NULL,
               vram_total REAL NOT NULL, vram_count INTEGER NOT NULL
             );
             CREATE TABLE IF NOT EXISTS hourly_telemetry(
               bucket INTEGER PRIMARY KEY, samples INTEGER NOT NULL,
               cpu_total REAL NOT NULL, ram_total REAL NOT NULL,
               gpu_total REAL NOT NULL, gpu_count INTEGER NOT NULL,
               temp_total REAL NOT NULL, temp_count INTEGER NOT NULL,
               vram_total REAL NOT NULL, vram_count INTEGER NOT NULL
             );"
        ).map_err(|e| e.to_string())?;
        Ok(Self(Mutex::new(conn)))
    }

    pub fn record(&self, point: &MetricPoint) -> Result<(), String> {
        let mut conn = self.0.lock().map_err(|_| "Telemetry lock poisoned")?;
        let tx = conn.transaction().map_err(|e| e.to_string())?;
        tx.execute(
            "INSERT INTO raw_telemetry(ts,cpu,ram,gpu,gpu_temp,vram_mb) VALUES (?1,?2,?3,?4,?5,?6)",
            params![point.timestamp, point.cpu, point.ram, point.gpu, point.gpu_temp, point.vram_mb]
        ).map_err(|e| e.to_string())?;
        for (table, unit) in [("minute_telemetry",60),("hourly_telemetry",3600)] {
            // Table identifiers are fixed program constants, never user input.
            let sql = format!(
                "INSERT INTO {table}(
                    bucket,samples,cpu_total,ram_total,gpu_total,gpu_count,
                    temp_total,temp_count,vram_total,vram_count
                 ) VALUES (?1,1,?2,?3,?4,?5,?6,?7,?8,?9)
                 ON CONFLICT(bucket) DO UPDATE SET
                   samples=samples+1,cpu_total=cpu_total+excluded.cpu_total,
                   ram_total=ram_total+excluded.ram_total,
                   gpu_total=gpu_total+excluded.gpu_total,
                   gpu_count=gpu_count+excluded.gpu_count,
                   temp_total=temp_total+excluded.temp_total,
                   temp_count=temp_count+excluded.temp_count,
                   vram_total=vram_total+excluded.vram_total,
                   vram_count=vram_count+excluded.vram_count"
            );
            tx.execute(&sql, params![
                point.timestamp / unit * unit,
                point.cpu.unwrap_or(0.0), point.ram.unwrap_or(0.0),
                point.gpu.unwrap_or(0.0), i64::from(point.gpu.is_some()),
                point.gpu_temp.unwrap_or(0.0), i64::from(point.gpu_temp.is_some()),
                point.vram_mb.unwrap_or(0.0), i64::from(point.vram_mb.is_some()),
            ]).map_err(|e| e.to_string())?;
        }
        tx.execute("DELETE FROM raw_telemetry WHERE ts < ?1", params![point.timestamp-86400])
          .map_err(|e| e.to_string())?;
        tx.execute("DELETE FROM minute_telemetry WHERE bucket < ?1", params![point.timestamp-30*86400])
          .map_err(|e| e.to_string())?;
        tx.commit().map_err(|e| e.to_string())
    }

    pub fn history(&self, window: &str) -> Result<Vec<MetricPoint>, String> {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).map_err(|e| e.to_string())?.as_secs() as i64;
        let (sql, since) = match window {
            "1h" => ("SELECT ts,cpu,ram,gpu,gpu_temp,vram_mb FROM raw_telemetry WHERE ts>=?1 ORDER BY ts", now-3600),
            "24h" => ("SELECT bucket,cpu_total/samples,ram_total/samples,
                       CASE WHEN gpu_count>0 THEN gpu_total/gpu_count ELSE NULL END,
                       CASE WHEN temp_count>0 THEN temp_total/temp_count ELSE NULL END,
                       CASE WHEN vram_count>0 THEN vram_total/vram_count ELSE NULL END
                       FROM minute_telemetry WHERE bucket>=?1 ORDER BY bucket", now-86400),
            "7d" => ("SELECT bucket,cpu_total/samples,ram_total/samples,
                       CASE WHEN gpu_count>0 THEN gpu_total/gpu_count ELSE NULL END,
                       CASE WHEN temp_count>0 THEN temp_total/temp_count ELSE NULL END,
                       CASE WHEN vram_count>0 THEN vram_total/vram_count ELSE NULL END
                       FROM hourly_telemetry WHERE bucket>=?1 ORDER BY bucket", now-7*86400),
            _ => return Err("Unsupported telemetry window".into()),
        };
        let conn = self.0.lock().map_err(|_| "Telemetry lock poisoned")?;
        let mut query = conn.prepare(sql).map_err(|e| e.to_string())?;
        let rows = query.query_map([since], |row| Ok(MetricPoint {
            timestamp: row.get(0)?, cpu: row.get(1)?, ram: row.get(2)?,
            gpu: row.get(3)?, gpu_temp: row.get(4)?, vram_mb: row.get(5)?,
        })).map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>,_>>().map_err(|e| e.to_string())
    }

    pub fn export_csv(&self, window: &str, directory: &Path) -> Result<String, String> {
        let points = self.history(window)?;
        std::fs::create_dir_all(directory).map_err(|e| e.to_string())?;
        let target = directory.join(format!("aurix-telemetry-{}.csv", window));
        let mut content = String::from("timestamp,cpu_percent,ram_percent,gpu_percent,gpu_temp_c,vram_mb\n");
        for item in points {
            fn cell(n: Option<f64>) -> String { n.map(|v| format!("{v:.2}")).unwrap_or_default() }
            content.push_str(&format!("{},{},{},{},{},{}\n",
              item.timestamp, cell(item.cpu), cell(item.ram), cell(item.gpu),
              cell(item.gpu_temp), cell(item.vram_mb)));
        }
        std::fs::write(&target, content).map_err(|e| e.to_string())?;
        Ok(target.display().to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_unbounded_window() {
        let store = TelemetryStore(Mutex::new(Connection::open_in_memory().unwrap()));
        assert!(store.history("all").is_err());
    }
}
