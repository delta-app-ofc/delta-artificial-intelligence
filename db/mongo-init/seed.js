const telemetry = db.getSiblingDB("db_delta_telemetry");
const appdb = db.getSiblingDB("db_delta_app");

telemetry.consumption_summary.drop();
appdb.user_preferences.drop();
appdb.alerts_history.drop();

const DAY_MS = 24 * 60 * 60 * 1000;
const NOW = Date.now();

/**
 * Gera janelas de consumo (uma lista de docs de consumption_summary).
 * @param {number} userId
 * @param {string} deviceId
 * 
 * @param {object} opts
 *   - days:    quantos dias para trás gerar
 *   - hours:   horas do dia com janela (ex.: [7, 12, 19])
 *   - litersForDayIndex(i): litros totais no dia, i = 0 (mais antigo) .. days-1
 *   - isAnomalous(i, hour): (opcional) marca a janela como anômala
 */
function buildWindows(userId, deviceId, opts) {
  const docs = [];
  for (let d = opts.days; d >= 1; d--) {
    const i = opts.days - d; 
    const totalDia = opts.litersForDayIndex(i);
    const litrosJanela = Math.round((totalDia / opts.hours.length) * 100) / 100;

    for (const hour of opts.hours) {
      const start = new Date(NOW - d * DAY_MS);
      start.setUTCHours(hour, 0, 0, 0);
      const finish = new Date(start.getTime() + 5 * 60 * 1000);

      docs.push({
        device_id: deviceId,
        user_id: NumberInt(userId),
        window_started_at: start,
        window_finished_at: finish,
        consumption_liters: litrosJanela,
        lpm_average: Math.round((litrosJanela / 5) * 100) / 100,
        anomaly_detected: opts.isAnomalous ? !!opts.isAnomalous(i, hour) : false,
      });
    }
  }
  return docs;
}

const u11 = buildWindows(11, "ESP3211", {
  days: 45,
  hours: [7, 12, 19],
  litersForDayIndex: (i) => 260 - i * 3,
});

const u12 = buildWindows(12, "ESP3212", {
  days: 45,
  hours: [7, 12, 19],
  litersForDayIndex: (i) => 150 + i * 3, 
});

const u14 = buildWindows(14, "ESP3214", {
  days: 30,
  hours: [3, 7, 12, 19],
  litersForDayIndex: (i) => 190 + (i % 5) * 4,
  isAnomalous: (i, hour) => hour === 3 && i >= 30 - 6,
});

const u15 = buildWindows(15, "ESP3215", {
  days: 30,
  hours: [7, 12, 19],
  litersForDayIndex: (i) => 175 + (i % 7) * 2,
});

telemetry.consumption_summary.insertMany([...u11, ...u12, ...u14, ...u15]);

telemetry.consumption_summary.createIndex(
  { user_id: 1, window_started_at: -1 },
  { name: "idx_user_window_time" }
);
telemetry.consumption_summary.createIndex({ device_id: 1 }, { name: "idx_device" });

appdb.user_preferences.insertMany([
  { user_id: NumberInt(11), daily_liters_target: NumberInt(400), notifications_enabled: true,
    quiet_hours: { start_hour: "22:00", end_hour: "06:00" }, dark_mode_enabled: false },
  { user_id: NumberInt(12), daily_liters_target: NumberInt(270), notifications_enabled: true,
    quiet_hours: { start_hour: "22:00", end_hour: "06:00" }, dark_mode_enabled: false },
  { user_id: NumberInt(14), daily_liters_target: NumberInt(300), notifications_enabled: true,
    quiet_hours: { start_hour: "23:00", end_hour: "07:00" }, dark_mode_enabled: true },
  { user_id: NumberInt(15), daily_liters_target: NumberInt(300), notifications_enabled: true,
    quiet_hours: { start_hour: "22:00", end_hour: "06:00" }, dark_mode_enabled: false },
]);
appdb.user_preferences.createIndex({ user_id: 1 }, { name: "idx_user_id_unique", unique: true });

appdb.alerts_history.insertMany([
  {
    device_id: "ESP3214",
    user_id: NumberInt(14),
    alert_type: "vazamento_continuo",
    triggered_at: new Date(NOW - 2 * DAY_MS),
    resolved_at: null,
    severity: "high",
  },
  {
    device_id: "ESP3214",
    user_id: NumberInt(14),
    alert_type: "fluxo_atipico",
    triggered_at: new Date(NOW - 20 * DAY_MS),
    resolved_at: new Date(NOW - 19 * DAY_MS),
    severity: "medium",
  },
]);
appdb.alerts_history.createIndex(
  { user_id: 1, triggered_at: -1 },
  { name: "idx_user_triggered_at_desc" }
);
appdb.alerts_history.createIndex(
  { device_id: 1, resolved_at: 1 },
  { name: "idx_device_unresolved_alerts", partialFilterExpression: { resolved_at: null } }
);

print("Delta seed: consumption_summary=" + telemetry.consumption_summary.countDocuments() +
      " user_preferences=" + appdb.user_preferences.countDocuments() +
      " alerts_history=" + appdb.alerts_history.countDocuments());
