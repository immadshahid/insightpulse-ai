import 'package:shared_preferences/shared_preferences.dart';

/// Small, non-secret app preferences (theme, period, last dataset).
/// The login token lives in secure storage instead (see [TokenStore]).
abstract class Prefs {
  String? getString(String key);
  Future<void> setString(String key, String value);
  Future<void> remove(String key);
}

class PrefKeys {
  const PrefKeys._();
  static const themeMode = 'theme_mode';
  static const period = 'period';
  static const datasetId = 'dataset_id';
  static const onboarded = 'onboarded';
  static String goal(String period) => 'goal_$period';
  static const serverUrl = 'server_url';
  static const all = {themeMode, period, datasetId, onboarded, serverUrl, 'goal_7d', 'goal_30d', 'goal_90d', 'goal_1y'};
}

class SharedPrefs implements Prefs {
  SharedPrefs._(this._prefs);

  final SharedPreferencesWithCache _prefs;

  static Future<SharedPrefs> load() async => SharedPrefs._(await SharedPreferencesWithCache.create(
        cacheOptions: const SharedPreferencesWithCacheOptions(allowList: PrefKeys.all),
      ));

  @override
  String? getString(String key) => _prefs.getString(key);

  @override
  Future<void> setString(String key, String value) => _prefs.setString(key, value);

  @override
  Future<void> remove(String key) => _prefs.remove(key);
}

/// In-memory preferences for tests.
class MemoryPrefs implements Prefs {
  MemoryPrefs([Map<String, String>? initial]) : values = {...?initial};

  final Map<String, String> values;

  @override
  String? getString(String key) => values[key];

  @override
  Future<void> setString(String key, String value) async => values[key] = value;

  @override
  Future<void> remove(String key) async => values.remove(key);
}
