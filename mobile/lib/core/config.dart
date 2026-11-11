/// Build-time configuration.
///
/// Point the app at your backend with
/// `flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000` (Android emulator)
/// or your machine's LAN address on a real phone.
class AppConfig {
  const AppConfig._();

  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://localhost:8000',
  );

  static String get apiRoot => '$apiBaseUrl/api/v1';
}
