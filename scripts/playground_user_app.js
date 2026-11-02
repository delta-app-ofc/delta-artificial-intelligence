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
  // Conexão: MONGODB_APP_URI.
  const app = db.getSiblingDB('db_delta_app');
  const available = new Set(app.getCollectionNames());
  for (const name of ['user_preferences', 'chat_sessions', 'alerts_history']) {
    if (!available.has(name)) throw new Error(`Coleção ausente: db_delta_app.${name}. Confira a conexão.`);
  }

  const oldPreferences = app.user_preferences.findOne({ user_id: oldUserId });
  const preferences = app.user_preferences.findOne({ user_id: userId });
  if (oldPreferences && !preferences) {
    app.user_preferences.updateOne(
      { _id: oldPreferences._id, user_id: oldUserId },
      { $set: { user_id: userId } },
    );
  } else if (oldPreferences && preferences) {
    print('Preferências já existem no novo ID: preservadas; o registro antigo também foi mantido.');
  }
  app.user_preferences.updateOne(
    { user_id: userId },
    { $setOnInsert: {
      user_id: userId,
      daily_liters_target: NumberInt(400),
      notifications_enabled: false,
      dark_mode_enabled: false,
      fixture_tag: fixtureTag,
    } },
    { upsert: true },
  );

  for (const collection of [app.chat_sessions, app.alerts_history]) {
    const result = collection.updateMany({ user_id: oldUserId }, { $set: { user_id: userId } });
    print(`${collection.getName()}: ${result.modifiedCount} registros migrados para 123456789.`);
  }

  app.alerts_history.updateMany(
    { user_id: userId, device_id: oldDeviceId },
    { $set: { device_id: deviceId } },
  );

  // Sessões existentes são preservadas. Uma sessão vazia só é criada quando faltam todas.
  if (app.chat_sessions.countDocuments({ user_id: userId }) === 0) {
    app.chat_sessions.updateOne(
      { user_id: userId, fixture_tag: fixtureTag },
      { $setOnInsert: {
        user_id: userId,
        started_at: now,
        last_activity_at: now,
        is_open: true,
        is_active: true,
        is_deleted: false,
        messages: [],
        fixture_tag: fixtureTag,
      } },
      { upsert: true },
    );
  }

  for (const collection of [app.user_preferences, app.chat_sessions, app.alerts_history]) {
    print(`${collection.getName()}: ${collection.countDocuments({ user_id: userId })} registros do usuário 123456789.`);
  }
  print('IDs de sessões preservados: referências de chat_feedback continuam válidas.');
})();
