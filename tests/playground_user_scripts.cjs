// Exercita a migração com coleções em memória; não abre conexão MongoDB.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const scenario = process.argv[2];
const oldId = 12345679;
const newId = 123456789;
const oldDevice = 'ESP32-TEST-JUIZ-12345679';
const newDevice = 'ESP32-TEST-JUIZ-123456789';
const state = {
  db_delta_app: { user_preferences: [], chat_sessions: [], alerts_history: [], chat_feedback: [] },
  db_delta_telemetry: { consumption_summary: [], device_status: [] },
};
let writes = 0;
let sequence = 0;

if (scenario === 'legacy' || scenario === 'existing_preferences') {
  state.db_delta_app.user_preferences.push({ _id: 'prefs-old', user_id: oldId, daily_liters_target: 350, dark_mode_enabled: true });
  state.db_delta_app.chat_sessions.push({ _id: 'session-old', user_id: oldId, started_at: new Date(), messages: [{ content: 'DADO SINTÉTICO PRESERVADO' }] });
  state.db_delta_app.alerts_history.push({ _id: 'alert-old', user_id: oldId, device_id: oldDevice });
  state.db_delta_app.chat_feedback.push({ _id: 'feedback', session_id: 'session-old', is_satisfied: true });
  state.db_delta_telemetry.consumption_summary.push({ _id: 'reading-old', user_id: oldId, device_id: oldDevice, consumption_liters: 2.75 });
  state.db_delta_telemetry.device_status.push({ _id: 'status-old', device_id: oldDevice, connectivity_status: 'offline' });
}
if (scenario === 'existing_preferences') {
  state.db_delta_app.user_preferences.push({ _id: 'prefs-new', user_id: newId, daily_liters_target: 675, dark_mode_enabled: false });
}
// Dados que nunca devem ser migrados ou renomeados.
state.db_delta_app.chat_sessions.push({ _id: 'unrelated-session', user_id: 55, messages: [] });
state.db_delta_telemetry.consumption_summary.push({ _id: 'unrelated-reading', user_id: 55, device_id: oldDevice, consumption_liters: 1.75 });
state.db_delta_telemetry.device_status.push({ _id: 'unrelated-status', device_id: 'OTHER', connectivity_status: 'offline' });

const matches = (doc, filter) => Object.entries(filter).every(([key, value]) => doc[key] === value);
function collection(database, name) {
  return {
    getName: () => name,
    findOne: filter => state[database][name].find(doc => matches(doc, filter)) ?? null,
    countDocuments: filter => state[database][name].filter(doc => matches(doc, filter)).length,
    updateOne(filter, update, options = {}) {
      let doc = this.findOne(filter);
      if (!doc && options.upsert) {
        doc = { _id: `generated-${++sequence}`, ...filter, ...(update.$setOnInsert ?? {}) };
        state[database][name].push(doc);
        writes++;
      }
      if (doc && update.$set) { Object.assign(doc, update.$set); writes++; }
      return { modifiedCount: doc ? 1 : 0 };
    },
    updateMany(filter, update) {
      const found = state[database][name].filter(doc => matches(doc, filter));
      found.forEach(doc => Object.assign(doc, update.$set));
      writes += found.length;
      return { modifiedCount: found.length };
    },
  };
}
function database(name, missing = false) {
  const result = { getCollectionNames: () => missing ? [] : Object.keys(state[name]) };
  for (const key of Object.keys(state[name])) result[key] = collection(name, key);
  return result;
}
function run(file, missing = false) {
  const context = {
    db: { getSiblingDB: name => database(name, missing) },
    NumberInt(value) { assert(Number.isInteger(value) && value >= -2147483648 && value <= 2147483647); return value; },
    print() {},
  };
  const filename = path.resolve('scripts', file);
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), context, { filename });
}
const scripts = ['playground_user_app.js', 'playground_user_telemetry.js'];
if (scenario === 'wrong_connection') {
  for (const file of scripts) assert.throws(() => run(file, true), /Coleção ausente/);
  assert.equal(writes, 0);
  process.exit(0);
}

scripts.forEach(file => run(file));
const once = JSON.stringify(state);
scripts.forEach(file => run(file));
assert.equal(JSON.stringify(state), once, 'Repetir a migração não deve duplicar ou modificar os registros novamente.');
assert.equal(state.db_delta_app.chat_sessions.find(doc => doc._id === 'unrelated-session').user_id, 55);
assert.equal(state.db_delta_telemetry.consumption_summary.find(doc => doc._id === 'unrelated-reading').device_id, oldDevice);
assert.equal(state.db_delta_telemetry.device_status.find(doc => doc._id === 'unrelated-status').connectivity_status, 'offline');
assert.equal(state.db_delta_telemetry.device_status.filter(doc => doc.device_id === newDevice).length, 1);
assert.equal(state.db_delta_app.user_preferences.filter(doc => doc.user_id === newId).length, 1);
if (scenario === 'legacy' || scenario === 'existing_preferences') {
  assert.equal(state.db_delta_app.chat_sessions.find(doc => doc._id === 'session-old').user_id, newId);
  assert.equal(state.db_delta_app.chat_sessions.find(doc => doc._id === 'session-old').messages[0].content, 'DADO SINTÉTICO PRESERVADO');
  assert.equal(state.db_delta_app.chat_feedback[0].session_id, 'session-old');
  const reading = state.db_delta_telemetry.consumption_summary.find(doc => doc._id === 'reading-old');
  assert.equal(reading.user_id, newId);
  assert.equal(reading.device_id, newDevice);
  assert.equal(reading.consumption_liters, 2.75);
  assert.equal(state.db_delta_app.alerts_history[0].device_id, newDevice);
  assert.equal(state.db_delta_telemetry.device_status.find(doc => doc.device_id === newDevice).connectivity_status, 'offline');
} else {
  assert.equal(state.db_delta_telemetry.consumption_summary.filter(doc => doc.user_id === newId).length, 0);
  assert.equal(state.db_delta_app.chat_sessions.filter(doc => doc.user_id === newId).length, 1);
}
const prefs = state.db_delta_app.user_preferences.find(doc => doc.user_id === newId);
assert.equal(prefs.daily_liters_target, scenario === 'existing_preferences' ? 675 : scenario === 'legacy' ? 350 : 400);
