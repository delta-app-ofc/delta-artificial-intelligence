/* global db, NumberInt, print */
// Preparação manual do usuário 123456789. Execute playground_user.sql primeiro.
// Execute este arquivo somente na conexão indicada pelo nome da variável de ambiente.
// Preserva os _id e os registros existentes do novo usuário; pode ser repetido.
(() => {
  const oldUserId = NumberInt(12345679);
  const userId = NumberInt(123456789);
  const oldDeviceId = 'ESP32-TEST-JUIZ-12345679';
  const deviceId = 'ESP32-TEST-JUIZ-123456789';
  const fixtureTag = 'playground-fbi-123456789';
  const now = new Date();
  // Conexão: MONGODB_TELEMETRY_URI. Ela é diferente da conexão do banco app.
  const telemetry = db.getSiblingDB('db_delta_telemetry');
  const available = new Set(telemetry.getCollectionNames());
  for (const name of ['consumption_summary', 'device_status']) {
    if (!available.has(name)) throw new Error(`Coleção ausente: db_delta_telemetry.${name}. Confira a conexão.`);
  }
  const result = telemetry.consumption_summary.updateMany(
    { user_id: oldUserId },
    { $set: { user_id: userId } },
  );
  print(`consumption_summary: ${result.modifiedCount} leituras migradas para 123456789.`);
  telemetry.consumption_summary.updateMany(
    { user_id: userId, device_id: oldDeviceId },
    { $set: { device_id: deviceId } },
  );
  const oldStatus = telemetry.device_status.findOne({ device_id: oldDeviceId });
  const status = telemetry.device_status.findOne({ device_id: deviceId });
  if (oldStatus && !status) {
    telemetry.device_status.updateOne(
      { _id: oldStatus._id, device_id: oldDeviceId },
      { $set: { device_id: deviceId } },
    );
  }
  telemetry.device_status.updateOne(
    { device_id: deviceId },
    { $setOnInsert: {
      device_id: deviceId,
      last_ping_at: now,
      connectivity_status: 'online',
      wifi_signal_rssi: 'good',
      firmware_version: 'PLAYGROUND-SYNTHETIC',
      battery_level: NumberInt(100),
      fixture_tag: fixtureTag,
    } },
    { upsert: true },
  );

  const count = telemetry.consumption_summary.countDocuments({ user_id: userId });
  print(`consumption_summary: ${count} leituras do usuário 123456789.`);
  if (count === 0) print('Sem histórico anterior: nenhuma leitura foi inventada; carregue dados pelo simulador se necessário.');
  print(`Dispositivo de teste: ${deviceId}. Nenhum outro dispositivo foi renomeado.`);
})();
